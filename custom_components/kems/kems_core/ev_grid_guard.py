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
# During measured EV charging in an independently confirmed cheap window,
# leave room for a 7.6 kW Ohme and normal household load. This is a battery
# Force Charge setpoint cap, not an EV throttle or a grid import-limit write.
_EV_CHEAP_BATTERY_CHARGE_CAP_KW = 5.0
_EV_CHEAP_GRID_IMPORT_RESERVE_KW = 0.75


def _nonnegative(value: float | None) -> float | None:
    if value is None or not isfinite(value):
        return None
    return max(float(value), 0.0)


def measured_ohme_ev_charge_active(snapshot: Snapshot) -> bool:
    """Fresh charger demand is a *hold-only* trigger, never a cheap-rate signal."""
    power = _nonnegative(snapshot.ev_power_kw)
    age = snapshot.ev_power_age_seconds
    return bool(
        snapshot.ev_connected is True
        and snapshot.ev_charging is True
        and power is not None
        and power > _EV_ACTIVE_KW
        and age is not None
        and 0 <= age <= _MAX_OHME_AGE_SECONDS
        and "ev_power_kw" not in snapshot.stale_fields
    )


def protect_measured_ohme_ev_hold(
    snapshot: Snapshot,
    control: ControlState,
    config: ControlConfig,
    *,
    eligible_for_hold_only: bool,
    held_floor_percent: float | None = None,
    bounded_pause: bool = False,
) -> ControlState:
    """Use the existing Self Use + physical MinSOC route during real EV draw.

    The native Ohme slot service may return an empty plan *while charging*.
    Fresh physical Ohme power and connected/charging state are a stronger
    battery-protection trigger, not proof of an Octopus discounted tariff.
    This guard never selects Force Charge or changes import rate.
    """
    if (
        not eligible_for_hold_only
        or snapshot.cheap_period_confirmed
        or snapshot.saving_session_active
        or control.operating_mode != "control"
        or control.desired_work_mode != "Self Use"
        or control.desired_battery_export_power_kw > 0.001
        or not control.data_fresh
        or not control.plan_safe
        or not config.control_enabled
        or not config.commissioned
        or config.emergency_stop
        or control.island_mode_active
        or not control.grid_available
        or control.alpha969_routing_shadow_only
        or control.site_import_limit_exceeded
    ):
        return control

    active = measured_ohme_ev_charge_active(snapshot)
    power = _nonnegative(snapshot.ev_power_kw)
    age = snapshot.ev_power_age_seconds
    paused = bool(
        not active
        and bounded_pause
        and held_floor_percent is not None
        and snapshot.ev_connected is True
        and snapshot.ev_charging is False
        and power is not None
        and power <= _EV_ACTIVE_KW
        and age is not None
        and 0 <= age <= _MAX_OHME_AGE_SECONDS
        and "ev_power_kw" not in snapshot.stale_fields
    )
    if not active and not paused:
        return control

    soc = snapshot.battery_soc
    if (
        soc is None
        or not isfinite(soc)
        or not 0 <= soc <= 100
        or "battery_soc" in snapshot.stale_fields
        or snapshot.source_data_age_seconds is None
        or snapshot.source_data_age_seconds > config.stale_data_seconds
    ):
        return replace(
            control,
            ev_grid_guard_status="observed_ohme_hold_blocked_no_fresh_soc",
            next_action=(
                "Ohme charging detected; physical SOC proof missing, "
                "no new EV hold write"
            ),
        )

    grid = _nonnegative(snapshot.grid_import_kw)
    discharge = _nonnegative(snapshot.battery_power_kw)
    limit = config.site_import_limit_kw
    if (
        grid is None
        or discharge is None
        or "grid_import_kw" in snapshot.stale_fields
        or "battery_power_kw" in snapshot.stale_fields
        or limit is None
        or not isfinite(limit)
        or limit <= 0
    ):
        return replace(
            control,
            ev_grid_guard_status="observed_ohme_hold_blocked_site_unknown",
            next_action="Ohme battery hold awaiting fresh CT and site-limit evidence",
        )
    projected_import = grid + discharge
    if projected_import > limit + 0.001:
        return replace(
            control,
            ev_grid_guard_status="observed_ohme_hold_blocked_site_limit",
            next_action="Ohme battery hold blocked by physical site-import limit",
        )

    held_soc = min(
        100.0,
        max(
            control.desired_min_soc_percent,
            float(ceil(soc) + 1),
            held_floor_percent or 0.0,
        ),
    )
    return replace(
        control,
        ev_grid_guard_status=(
            "ev_battery_hold_ohme_measured"
            if active
            else "ev_battery_hold_ohme_brief_pause"
        ),
        desired_work_mode="Self Use",
        desired_charge_power_kw=0.0,
        desired_battery_to_home_power_kw=0.0,
        desired_battery_export_power_kw=0.0,
        desired_total_discharge_power_kw=0.0,
        desired_grid_export_allowed=False,
        desired_min_soc_percent=held_soc,
        grid_bypass_power_kw=round(projected_import, 3),
        total_site_import_kw=round(projected_import, 3),
        site_import_headroom_kw=round(limit - projected_import, 3),
        site_import_limit_exceeded=False,
        next_action=(
            "Fresh Ohme EV charging: existing Self Use physical MinSOC hold; "
            "no daytime cheap tariff or battery Force Charge authority"
            if active
            else "Short Ohme pause: retain verified battery floor until charging ends"
        ),
    )


def protect_pending_intelligent_ev_hold(
    snapshot: Snapshot,
    control: ControlState,
    config: ControlConfig,
    *,
    no_paid_export_mode: bool,
    held_floor_percent: float | None = None,
) -> ControlState:
    """Apply a hold-only guard while Intelligent window timestamps catch up.

    This is deliberately narrower than cheap-period authority. It may only
    raise the existing Self Use MinSOC floor when Octopus already says the
    Intelligent slot is ON, Ohme is actively charging, cheap-rate evidence is
    corroborated, and the only missing confirmation is the start/end window.
    It never authorises Force Charge.
    """
    evidence = (
        snapshot.intelligent_slot_evidence
        if isinstance(snapshot.intelligent_slot_evidence, dict)
        else {}
    )
    pending_evidence = bool(
        evidence.get("enabled") is True
        and evidence.get("confirmed") is False
        and evidence.get("reason") == "Intelligent start/end window is unavailable"
        and evidence.get("octopus_intelligent_slot") is True
        and evidence.get("octopus_price_corroborated") is True
        and evidence.get("ohme_connected") is True
        and evidence.get("ohme_charging") is True
        and evidence.get("ohme_power_active") is True
    )
    if (
        not pending_evidence
        or snapshot.cheap_period_confirmed
        or snapshot.intelligent_slot_source_fresh is not True
        or snapshot.saving_session_active
        or control.operating_mode != "control"
        or control.operating_reason != "awaiting_export_tariff"
        or control.desired_work_mode != "Self Use"
        or control.desired_grid_export_allowed
        or control.desired_battery_export_power_kw > 0.001
        or not control.data_fresh
        or not control.plan_safe
        or not no_paid_export_mode
        or config.emergency_stop
        or control.island_mode_active
        or not control.grid_available
        or control.alpha969_routing_shadow_only
    ):
        return control

    ev = _nonnegative(snapshot.ev_power_kw)
    if (
        snapshot.ev_connected is not True
        or snapshot.ev_charging is not True
        or ev is None
        or ev <= _EV_ACTIVE_KW
        or snapshot.ev_power_age_seconds is None
        or not 0 <= snapshot.ev_power_age_seconds <= _MAX_OHME_AGE_SECONDS
        or "ev_power_kw" in snapshot.stale_fields
    ):
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
            ev_grid_guard_status="pending_intelligent_hold_blocked_no_fresh_soc",
            next_action=(
                "Intelligent is ON and Ohme is charging, but the pending EV hold "
                "cannot be armed without fresh physical battery SOC."
            ),
        )

    grid = _nonnegative(snapshot.grid_import_kw)
    battery_discharge = _nonnegative(snapshot.battery_power_kw)
    if config.site_import_limit_kw is not None:
        if (
            grid is None
            or battery_discharge is None
            or "grid_import_kw" in snapshot.stale_fields
            or "battery_power_kw" in snapshot.stale_fields
        ):
            return replace(
                control,
                ev_grid_guard_status="pending_intelligent_hold_blocked_site_unknown",
                next_action=(
                    "Pending Intelligent EV hold is blocked until grid and battery "
                    "power are fresh enough to prove site-import headroom."
                ),
            )
        projected_import = grid + battery_discharge
        if projected_import > config.site_import_limit_kw + 0.001:
            return replace(
                control,
                ev_grid_guard_status="pending_intelligent_hold_blocked_site_limit",
                next_action=(
                    "Pending Intelligent EV hold is blocked because replacing "
                    "battery discharge with grid import could exceed the site limit."
                ),
            )
    else:
        projected_import = (
            None
            if grid is None or battery_discharge is None
            else grid + battery_discharge
        )

    held_soc = min(
        100.0,
        max(
            control.desired_min_soc_percent,
            float(ceil(soc) + 1),
            held_floor_percent or 0.0,
        ),
    )
    headroom = (
        None
        if config.site_import_limit_kw is None or projected_import is None
        else round(config.site_import_limit_kw - projected_import, 3)
    )
    return replace(
        control,
        ev_grid_guard_status="ev_battery_hold_pending_intelligent_window",
        desired_work_mode="Self Use",
        desired_charge_power_kw=0.0,
        desired_min_soc_percent=held_soc,
        desired_battery_to_home_power_kw=0.0,
        desired_total_discharge_power_kw=0.0,
        grid_bypass_power_kw=(
            control.grid_bypass_power_kw
            if projected_import is None
            else round(projected_import, 3)
        ),
        total_site_import_kw=(
            control.total_site_import_kw
            if projected_import is None
            else round(projected_import, 3)
        ),
        site_import_headroom_kw=headroom,
        site_import_limit_exceeded=False,
        next_action=(
            "Intelligent is ON and Ohme is actively charging while Octopus window "
            "timestamps are still settling: temporarily hold physical battery SOC "
            "with Self Use + MinSOC only. Do not Force Charge until the full "
            "Intelligent window is confirmed."
        ),
    )


def _balanced_overnight_site_demand(
    snapshot: Snapshot, house: float, ev: float, grid: float
) -> float | None:
    """Corroborate a no-charge hold, not new charging or EV isolation.

    Only use this narrow fallback when the physical readings agree that
    FoxESS Load already represents total demand. At night, unchanged zero
    PV/export readings may be cohort-corroborated; changing load, battery
    and CT readings must have fresh, closely matched raw timestamps.
    """
    if (
        snapshot.off_peak is not True
        or snapshot.ev_load_in_house_load is not None
        or snapshot.solar_power_kw != 0.0
        or snapshot.grid_export_kw != 0.0
        or snapshot.battery_power_kw is None
        or not isfinite(snapshot.battery_power_kw)
        or house < ev
        or {"solar_power_kw", "grid_export_kw", "battery_power_kw"}
        & set(snapshot.stale_fields)
    ):
        return None
    ages = [
        snapshot.source_age_seconds.get(key)
        for key in ("house_load_kw", "battery_power_kw", "grid_import_kw")
    ]
    if any(age is None or not isfinite(age) or not 0 <= age <= 30 for age in ages):
        return None
    if max(ages) - min(ages) > 5:
        return None
    # Signed battery power also subtracts existing charge demand from CT
    # import. AC conversion losses remain conservatively in the bound.
    supply = grid + snapshot.battery_power_kw
    if abs(supply - house) > 0.5 or supply < ev:
        return None
    return max(supply, house)


def _charging_overnight_hold_bound(
    snapshot: Snapshot,
    control: ControlState,
    config: ControlConfig,
    house: float,
    ev: float,
    grid: float,
) -> float | None:
    """Suspend existing charge on a bounded CT-only hold, not new charge.

    FoxESS may not report an unchanged negative battery power at the same
    instant as its load and CT. Only accept this fallback for a recent
    charging reading, independently fresh aligned CT/load, and a consistent
    night-time balance. Use the entire measured CT import as the conservative
    bound; never infer a new charging setpoint or relax the discharge proof.
    """
    battery = snapshot.battery_power_kw
    limit = config.site_import_limit_kw
    if (
        snapshot.off_peak is not True
        or "off_peak" in snapshot.tariff_stale_fields
        or snapshot.ev_load_in_house_load is not None
        or snapshot.solar_power_kw != 0.0
        or snapshot.grid_export_kw != 0.0
        or battery is None
        or not isfinite(battery)
        or battery >= -0.001
        or limit is None
        or not isfinite(limit)
        or grid + _EV_CHEAP_GRID_IMPORT_RESERVE_KW > limit
        or not control.data_fresh
        or not config.control_enabled
        or not config.commissioned
        or control.eps_critical
        or control.desired_grid_export_allowed
        or control.desired_battery_export_power_kw > 0.001
        or control.operating_reason == "agile_rolling_happy_hour_charge"
        or {"solar_power_kw", "grid_export_kw", "battery_power_kw"}
        & set(snapshot.stale_fields)
        or not ev <= house <= grid
        or abs(grid + battery - house) > 0.5
    ):
        return None
    ages = snapshot.source_age_seconds
    ct = ages.get("grid_import_kw")
    load = ages.get("house_load_kw")
    bat = ages.get("battery_power_kw")
    if any(
        age is None or not isfinite(age) or not 0 <= age <= 30 for age in (ct, load)
    ):
        return None
    if (
        abs(ct - load) > 5
        or bat is None
        or not isfinite(bat)
        or not 0 <= bat <= min(config.stale_data_seconds, 90.0)
    ):
        return None
    return grid


def regular_overnight_grid_supply(
    snapshot: Snapshot,
    control: ControlState,
    config: ControlConfig,
    *,
    verified_overnight_hold: bool = False,
) -> ControlState:
    """Dedicated fixed-cheap whole-bus policy, independent of EV hold state.

    EV measurements affect the charge allowance, not the desired floor.
    A conservative load estimate that exceeds the limit cannot authorise
    charging. A fresh physical CT plus discharge bound can establish a
    zero-charge hold without assuming EV membership.
    """
    if (
        snapshot.off_peak is not True
        or not snapshot.cheap_period_confirmed
        or "off_peak" in snapshot.tariff_stale_fields
        or snapshot.saving_session_active
        or control.operating_mode != "control"
        or control.operating_reason
        not in {
            "awaiting_export_tariff_charge",
            "confirmed_cheap_charge",
            "agile_rolling_cheap_charge",
        }
        or not config.control_enabled
        or not config.commissioned
        or config.emergency_stop
        or not control.grid_available
        or control.island_mode_active
        or control.eps_critical
        or control.alpha969_routing_shadow_only
        or control.desired_grid_export_allowed
        or control.desired_battery_export_power_kw > 0.001
    ):
        return control
    prior_site_only = (
        control.site_import_limit_exceeded
        and control.blocked_reason
        == "Configured site-import limit leaves no safe charging headroom"
    )
    if not control.data_fresh or not (control.plan_safe or prior_site_only):
        return control
    grid = _nonnegative(snapshot.grid_import_kw)
    house = _nonnegative(snapshot.house_load_kw)
    ev = _nonnegative(snapshot.ev_power_kw)
    limit = config.site_import_limit_kw
    if (
        grid is None
        or house is None
        or limit is None
        or not isfinite(limit)
        or limit <= 0
        or grid > limit + 0.001
        or {"grid_import_kw", "house_load_kw"} & set(snapshot.stale_fields)
    ):
        return replace(
            control,
            desired_charge_power_kw=0.0,
            desired_work_mode="No change",
            plan_safe=False,
            site_import_limit_exceeded=True,
            blocked_reason="Regular cheap-period physical site-import safety veto",
        )
    ev_known = bool(
        ev is not None
        and snapshot.ev_power_age_seconds is not None
        and 0 <= snapshot.ev_power_age_seconds <= _MAX_OHME_AGE_SECONDS
        and "ev_power_kw" not in snapshot.stale_fields
        and snapshot.ev_charging is not None
    )
    ev_active = bool(ev_known and (snapshot.ev_charging or ev > _EV_ACTIVE_KW))
    demand = max(house, control.grid_bypass_power_kw, 0.0)
    if ev_active and snapshot.ev_load_in_house_load is not True:
        demand += ev
    charge_known = ev_known and (
        not ev_active or snapshot.ev_load_in_house_load is not None
    )
    # CT contains existing charging demand. Never subtract it to establish
    # a new charge target on uncertain scope. For a hold, CT plus the full
    # measured battery discharge conservatively bounds replacement import.
    battery = snapshot.battery_power_kw
    ages = snapshot.source_age_seconds
    aligned = all(
        ages.get(key) is not None and 0 <= ages[key] <= 30
        for key in ("grid_import_kw", "battery_power_kw")
    )
    physical_bound = None
    if (
        aligned
        and abs(ages["grid_import_kw"] - ages["battery_power_kw"]) <= 5
        and battery is not None
        and isfinite(battery)
        and "battery_power_kw" not in snapshot.stale_fields
    ):
        physical_bound = grid + max(battery, 0.0)
    if physical_bound is not None and physical_bound > limit + 0.001:
        return replace(
            control,
            desired_work_mode="No change",
            desired_charge_power_kw=0.0,
            plan_safe=False,
            site_import_limit_exceeded=True,
            blocked_reason="Regular cheap-period replacement import exceeds site limit",
        )
    hold_only = not charge_known or demand > limit
    if (
        hold_only
        and physical_bound is None
        and ev_active
        and verified_overnight_hold
    ):
        physical_bound = _charging_overnight_hold_bound(
            snapshot, control, config, house, ev, grid
        )
    if hold_only:
        if physical_bound is not None:
            demand = physical_bound
        elif demand > limit or not ev_known:
            # Retain safety veto without claiming a proven replacement load.
            return replace(
                control,
                desired_work_mode="No change",
                desired_charge_power_kw=0.0,
                plan_safe=False,
                site_import_limit_exceeded=True,
                blocked_reason="Regular cheap-period replacement demand unverified",
            )
    charge = min(
        0.0 if hold_only else max(control.desired_charge_power_kw, 0.0),
        max(config.max_charge_kw, 0.0),
        _EV_CHEAP_BATTERY_CHARGE_CAP_KW if ev_active else config.max_charge_kw,
        max(limit - demand - _EV_CHEAP_GRID_IMPORT_RESERVE_KW, 0.0),
    )
    return replace(
        control,
        ev_grid_guard_status="regular_overnight_grid_supply",
        desired_min_soc_percent=100.0,
        desired_work_mode="Force Charge" if charge > 0.001 else "Self Use",
        desired_charge_power_kw=round(charge, 3),
        desired_battery_to_home_power_kw=0.0,
        desired_battery_export_power_kw=0.0,
        desired_total_discharge_power_kw=0.0,
        desired_grid_export_allowed=False,
        grid_bypass_power_kw=round(demand, 3),
        total_site_import_kw=round(demand + charge, 3),
        site_import_headroom_kw=round(limit - demand - charge, 3),
        site_import_limit_exceeded=False,
        plan_safe=True,
        blocked_reason="" if prior_site_only else control.blocked_reason,
        next_action=(
            "Regular overnight: whole-site grid supply, 100% on-grid MinSOC; "
            f"battery charge target {charge:.3f} kW"
        ),
    )


def protect_fixed_overnight_grid_supply(
    snapshot: Snapshot, control: ControlState, config: ControlConfig
) -> ControlState:
    """Keep the whole bus on grid during the confirmed regular cheap window.

    The reviewed 100% on-grid MinSOC hold is independent of EV presence and
    the requested charge target. This does not authorise charging outside
    the regular window, waive a failed plan, or alter Happy Hour dispatch.
    """
    if (
        snapshot.off_peak is not True
        or not snapshot.cheap_period_confirmed
        or "off_peak" in snapshot.tariff_stale_fields
        or snapshot.saving_session_active
        or control.operating_mode != "control"
        or control.operating_reason
        not in {
            "awaiting_export_tariff_charge",
            "confirmed_cheap_charge",
            "agile_rolling_cheap_charge",
        }
        or control.desired_work_mode not in {"Self Use", "Force Charge"}
        or not control.data_fresh
        or not control.plan_safe
        or control.site_import_limit_exceeded
        or control.desired_grid_export_allowed
        or control.desired_battery_export_power_kw > 0.001
        or control.alpha969_routing_shadow_only
        or not config.control_enabled
        or not config.commissioned
        or config.emergency_stop
        or control.island_mode_active
        or not control.grid_available
        or control.eps_critical
    ):
        return control
    grid = _nonnegative(snapshot.grid_import_kw)
    limit = config.site_import_limit_kw
    if grid is None or (
        limit is not None and (not isfinite(limit) or grid > limit + 0.001)
    ):
        return replace(
            control,
            desired_charge_power_kw=0.0,
            desired_work_mode="No change",
            plan_safe=False,
            site_import_limit_exceeded=True,
            blocked_reason="Regular cheap-period physical site-import safety veto",
        )
    charge = max(control.desired_charge_power_kw, 0.0)
    return replace(
        control,
        desired_min_soc_percent=100.0,
        desired_work_mode="Force Charge" if charge > 0.001 else "Self Use",
        desired_battery_to_home_power_kw=0.0,
        desired_total_discharge_power_kw=0.0,
        next_action=(
            control.next_action
            + "; regular cheap window: maintain 100% on-grid MinSOC discharge hold"
        ),
    )


def protect_live_cheap_ev(
    snapshot: Snapshot,
    control: ControlState,
    config: ControlConfig,
    *,
    no_paid_export_mode: bool,
    held_floor_percent: float | None = None,
    verified_overnight_hold: bool = False,
) -> ControlState:
    """Guard a confirmed-cheap live plan when Ohme draws power or is unknown.

    EV is conservatively added to FoxESS Load until its membership is proven.
    This prevents extra battery-charge requests from exceeding site headroom.
    The real floor is raised to a rounded physical SoC plus a small guard.
    All effects remain on the already-reviewed work mode/MinSOC command path.
    """
    if (
        control.operating_mode != "control"
        or control.operating_reason
        not in {
            "awaiting_export_tariff_charge",
            "confirmed_cheap_charge",
            "agile_rolling_cheap_charge",
            "agile_rolling_happy_hour_charge",
        }
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
    # Limit the *new* charge setpoint while Ohme is measurably charging: the
    # 5 kW ceiling and spare import margin lower the risk of the inverter
    # leaving Force Charge as the EV and household load fluctuate. The
    # measured over-limit veto remains fail-closed; never bypass safety or
    # assume that reducing charge independently isolates battery from the EV.
    observed_over_limit = grid > limit + 0.001
    balanced_hold_demand = (
        _balanced_overnight_site_demand(snapshot, house, ev, grid)
        if conservative_demand > limit and not observed_over_limit
        else None
    )
    charging_hold_bound = (
        _charging_overnight_hold_bound(snapshot, control, config, house, ev, grid)
        if verified_overnight_hold
        and conservative_demand > limit
        and not observed_over_limit
        and balanced_hold_demand is None
        else None
    )
    if charging_hold_bound is not None:
        balanced_hold_demand = charging_hold_bound
    if (
        balanced_hold_demand is not None
        and balanced_hold_demand + _EV_CHEAP_GRID_IMPORT_RESERVE_KW <= limit
    ):
        # Avoid releasing the protective floor on a false double count.
        # This snapshot can support a hold only; wait for proven membership
        # before resuming any additional battery charging.
        conservative_demand = balanced_hold_demand
    else:
        balanced_hold_demand = None
    charge = min(
        (
            0.0
            if observed_over_limit or balanced_hold_demand is not None
            else max(control.desired_charge_power_kw, 0.0)
        ),
        max(config.max_charge_kw, 0.0),
        _EV_CHEAP_BATTERY_CHARGE_CAP_KW,
        max(limit - conservative_demand - _EV_CHEAP_GRID_IMPORT_RESERVE_KW, 0.0),
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
            f"EV active: cheap battery charging target {charge:.3f} kW, "
            "capped at 5 kW with 0.75 kW grid-import reserve; "
            "physical MinSOC protects the shared home/EV bus, not "
            "independent house-only battery output control."
            + (
                " Overnight CT-only no-charge hold: recent charging report "
                "is asynchronous; keep the entire measured CT import as the "
                "bound without assuming EV load membership."
                if charging_hold_bound is not None
                else (
                    " Corroborated overnight CT/battery balance: suspend charge "
                    "without releasing the battery hold while EV scope is uncertain."
                    if balanced_hold_demand is not None
                    else ""
                )
            )
        ),
    )
