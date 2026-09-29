"""Conservative *live* EV battery-hold policy using reviewed FoxESS controls.

A KH inverter and Ohme share a downstream AC bus. MinSOC-on-grid can inhibit
battery discharge, but cannot independently dispatch battery energy to one
consumer circuit. Never mistake this fallback for EV/house source isolation.
The only resulting physical actions remain the reviewed Self Use, confirmed
cheap Force Charge and MinSOC-on-grid route in foxess_control_backend.
"""

from __future__ import annotations

from dataclasses import replace
from math import ceil, isfinite

from .models import ControlConfig, ControlState, Snapshot

_MAX_OHME_AGE_SECONDS = 90.0
_EV_ACTIVE_KW = 0.25


def _nonnegative(value: float | None) -> float | None:
    if value is None or not isfinite(value):
        return None
    return max(float(value), 0.0)


def protect_live_cheap_ev(
    snapshot: Snapshot,
    control: ControlState,
    config: ControlConfig,
    *,
    no_paid_export_mode: bool,
    held_floor_percent: float | None = None,
) -> ControlState:
    """Guard a confirmed-cheap live plan when Ohme draws power or is unknown.

    EV is conservatively added to FoxESS Load until its membership is proven.
    This prevents extra battery-charge requests from exceeding site headroom.
    The real floor is raised to a rounded physical SoC plus a small guard.
    All effects remain on the already-reviewed work mode/MinSOC command path.
    """
    if (
        control.operating_mode != "control"
        or control.operating_reason != "awaiting_export_tariff_charge"
        or not no_paid_export_mode
        or not snapshot.cheap_period_confirmed
        or snapshot.saving_session_active
        or config.emergency_stop
        or control.island_mode_active
        or not control.grid_available
        or control.alpha969_routing_shadow_only
    ):
        return control

    ev = _nonnegative(snapshot.ev_power_kw)
    explicit_stop = bool(
        snapshot.ev_charging is False
        and ev is not None
        and ev <= _EV_ACTIVE_KW
        and snapshot.ev_power_age_seconds is not None
        and snapshot.ev_power_age_seconds <= _MAX_OHME_AGE_SECONDS
    )
    ev_prearm = bool(
        snapshot.ev_connected is True
        and snapshot.ev_charging is False
        and ev is not None
        and ev <= _EV_ACTIVE_KW
        and snapshot.ev_power_age_seconds is not None
        and 0 <= snapshot.ev_power_age_seconds <= _MAX_OHME_AGE_SECONDS
    )
    ev_active = bool(
        snapshot.ev_charging is True
        or (ev is not None and ev > _EV_ACTIVE_KW)
        or (snapshot.ev_connected is True and snapshot.ev_charging is None)
        or (held_floor_percent is not None and not explicit_stop)
    )
    if not ev_active and not ev_prearm:
        return control

    soc = snapshot.battery_soc
    if (
        soc is None
        or not isfinite(soc)
        or "battery_soc" in snapshot.stale_fields
        or snapshot.source_data_age_seconds is None
        or snapshot.source_data_age_seconds > config.stale_data_seconds
    ):
        return replace(
            control,
            ev_grid_guard_status="blocked_no_fresh_physical_soc",
            desired_work_mode="No change",
            desired_charge_power_kw=0.0,
            plan_safe=False,
            blocked_reason=(
                "EV active: no fresh physical battery SOC for safe MinSOC hold"
            ),
        )

    # MinSOC-on-grid is a *whole-bus* floor, not a per-circuit power limit.
    # A one-percentage-point buffer avoids relying on an exact rounded SOC.
    held_soc = min(
        100.0,
        max(
            control.desired_min_soc_percent,
            float(ceil(soc) + 1),
            held_floor_percent or 0.0,
        ),
    )
    if ev_prearm and not ev_active:
        # Arm the physical floor before Ohme begins drawing.  Preserve the
        # existing confirmed-cheap battery charge decision; only the MinSOC
        # floor changes, so a later EV ramp cannot immediately pull energy
        # from the battery while the next coordinator scan catches up.
        return replace(
            control,
            ev_grid_guard_status="ev_battery_hold_prearmed",
            desired_min_soc_percent=held_soc,
            desired_battery_to_home_power_kw=0.0,
            desired_total_discharge_power_kw=0.0,
            next_action=(
                "EV connected in a confirmed cheap window: pre-arm the physical "
                "battery MinSOC floor before charging starts while preserving the "
                "existing safe cheap-charge decision."
            ),
        )

    ev_fresh = bool(
        snapshot.ev_charging is True
        and ev is not None
        and ev > _EV_ACTIVE_KW
        and snapshot.ev_power_age_seconds is not None
        and 0 <= snapshot.ev_power_age_seconds <= _MAX_OHME_AGE_SECONDS
        and "ev_power_kw" not in snapshot.stale_fields
    )
    house = _nonnegative(snapshot.house_load_kw)
    grid = _nonnegative(snapshot.grid_import_kw)
    limit = config.site_import_limit_kw
    if (
        not ev_fresh
        or house is None
        or "house_load_kw" in snapshot.stale_fields
        or grid is None
        or "grid_import_kw" in snapshot.stale_fields
        or limit is None
        or not isfinite(limit)
        or limit <= 0
    ):
        return replace(
            control,
            ev_grid_guard_status="battery_hold_ev_or_site_unverified",
            desired_work_mode="Self Use",
            desired_charge_power_kw=0.0,
            desired_min_soc_percent=held_soc,
            desired_battery_to_home_power_kw=0.0,
            desired_total_discharge_power_kw=0.0,
            next_action=(
                "Hold physical battery SOC while EV/site readings are incomplete; "
                "house and EV may both import from cheap grid. No new Force Charge."
            ),
        )

    # The load is a whole-site value *only* when repeated physical telemetry
    # has proved Ohme is inside it. In every other case add Ohme once as a
    # conservative upper bound, never pretend the measurement split is proven.
    conservative_demand = max(house, control.grid_bypass_power_kw, 0.0)
    if snapshot.ev_load_in_house_load is not True:
        conservative_demand += ev
    # Actual CT import can already include an existing Force Charge request.
    # Adding it again to planned charge would double-count and oscillate the
    # controller. Use CT import only as an independent over-limit veto.
    observed_over_limit = grid > limit + 0.001
    charge = min(
        0.0 if observed_over_limit else max(control.desired_charge_power_kw, 0.0),
        max(config.max_charge_kw, 0.0),
        max(limit - conservative_demand, 0.0),
    )
    total = conservative_demand + charge
    # The reviewed cheap planner may have rejected its *uncapped* 7 kW
    # request solely for import headroom. Re-evaluate that one condition
    # after reducing charge rather than leaving a safe hold falsely blocked.
    prior_site_only_failure = bool(
        control.site_import_limit_exceeded
        and control.blocked_reason
        == "Configured site-import limit leaves no safe charging headroom"
    )
    safe = (
        (control.plan_safe or prior_site_only_failure)
        and not observed_over_limit
        and total <= limit + 0.001
    )
    guard_status = (
        "ev_battery_hold_with_cheap_charge" if charge > 0.001 else "ev_battery_hold"
    )
    if snapshot.ev_load_in_house_load is not True:
        guard_status += "_conservative_scope"
    if observed_over_limit:
        guard_status = "observed_site_import_limit_exceeded"
    return replace(
        control,
        ev_grid_guard_status=guard_status,
        desired_work_mode="Force Charge" if charge > 0.001 else "Self Use",
        desired_charge_power_kw=round(charge, 3),
        desired_min_soc_percent=held_soc,
        desired_battery_to_home_power_kw=0.0,
        desired_total_discharge_power_kw=0.0,
        grid_bypass_power_kw=round(conservative_demand, 3),
        total_site_import_kw=round(total, 3),
        site_import_headroom_kw=round(limit - total, 3),
        site_import_limit_exceeded=not safe,
        plan_safe=safe,
        blocked_reason=(
            "Observed grid import exceeds configured site limit"
            if observed_over_limit
            else "" if safe and prior_site_only_failure else control.blocked_reason
        ),
        next_action=(
            "EV active: hold battery with physical MinSOC and use confirmed "
            "cheap grid for the shared home/EV bus; this does not provide "
            "independent house-only battery output control."
        ),
    )
