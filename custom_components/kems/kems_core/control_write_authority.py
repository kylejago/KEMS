"""Pure authority gate for bounded FoxESS control."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from .models import ControlState

_EPSILON_KW = 0.001


@dataclass(frozen=True, slots=True)
class FoxESSControlDecision:
    """One deterministic decision about whether KEMS may write FoxESS."""

    backend_available: bool
    commands_permitted: bool
    action: str
    reason: str
    force_charge_power_kw: float | None = None
    force_discharge_power_kw: float | None = None
    export_power_limit_w: float | None = None
    export_commissioning_stage_limited: bool = False
    min_soc_on_grid_percent: float | None = None


def repair_contaminated_min_soc_baseline(
    previous_min_soc_on_grid: float | None,
    *,
    observed_min_soc_on_grid: float | None,
    last_verified_min_soc_on_grid: float | None,
    minimum_min_soc_on_grid: float | None,
    requested_noncheap_min_soc: float | None,
) -> float | None:
    """Repair a persisted baseline only when a prior EV hold proves contamination.

    Alpha9.81 must not let a temporary KEMS EV MinSOC hold become the remembered
    non-cheap baseline after restart. A repair is deliberately narrow: the
    stored baseline must be above the current normal non-cheap request, the live
    readback and KEMS' last physical EV-hold verification must both match that
    stored value, and the reviewed Home Assistant number entity must expose a
    lower minimum. Otherwise the existing captured baseline is preserved.
    """
    if previous_min_soc_on_grid is None:
        return None

    values = (
        previous_min_soc_on_grid,
        observed_min_soc_on_grid,
        last_verified_min_soc_on_grid,
        minimum_min_soc_on_grid,
        requested_noncheap_min_soc,
    )
    try:
        previous, observed, verified, minimum, requested = (
            float(value) if value is not None else None for value in values
        )
    except (TypeError, ValueError):
        return previous_min_soc_on_grid

    if any(
        value is None or not isfinite(value) or not 0.0 <= value <= 100.0
        for value in (previous, observed, verified, minimum, requested)
    ):
        return previous_min_soc_on_grid

    if previous <= requested + 0.05:
        return round(previous, 1)
    if abs(observed - previous) > 0.05:
        return round(previous, 1)
    if abs(verified - previous) > 0.05:
        return round(previous, 1)
    if minimum + 0.05 >= previous:
        return round(previous, 1)
    return round(minimum, 1)


def resolve_live_min_soc_on_grid(
    decision: FoxESSControlDecision,
    *,
    cheap_period_confirmed: bool,
    previous_min_soc_on_grid: float | None,
    pending_intelligent_ev_hold_active: bool = False,
) -> float | None:
    """Return the physically safe MinSOC target for the reviewed live write.

    The normal KEMS reserve is a planning/discharge target, not permission to
    buy daytime grid energy. Outside a confirmed cheap period, Self Use and
    paid-export Force Discharge preserve the pre-KEMS MinSOC-on-grid baseline
    instead of raising it to the planner/export reserve. The only exception is
    the Alpha9.76 hold-only pending Intelligent EV state, which may retain its
    requested MinSOC without granting cheap or Force Charge authority.
    Confirmed-cheap Self Use/Force Charge paths retain their requested MinSOC,
    including the Alpha9.70 EV battery-hold floor.
    """
    requested = decision.min_soc_on_grid_percent
    if (
        cheap_period_confirmed
        or pending_intelligent_ev_hold_active
        or decision.action == "force_charge"
    ):
        return requested
    if previous_min_soc_on_grid is None:
        return None
    return round(float(previous_min_soc_on_grid), 1)


def should_freeze_owned_ev_hold(
    *,
    owned_by_kems: bool,
    latched_min_soc_percent: float | None,
    last_applied_action: str | None,
    observed_min_soc_on_grid_percent: float | None,
    last_verified_min_soc_on_grid_percent: float | None,
    cheap_period_confirmed: bool,
    source_uncertainty_grace_active: bool,
    no_paid_export_mode: bool,
    ev_connected: bool | None,
    operating_mode: str,
    master_control_enabled: bool,
    user_commissioned: bool,
    emergency_stop: bool,
    island_mode_active: bool,
    grid_available: bool,
    pending_intelligent_ev_hold_active: bool = False,
) -> bool:
    """Return whether an already-applied cheap-window EV hold must be frozen.

    Freeze means *no new FoxESS writes*. It preserves only a physically
    verified KEMS-owned Self Use + MinSOC state through transient telemetry or
    commissioning-readiness loss. A fresh readback below the latched floor
    always blocks freeze. A confirmed-session hold may fall back to its last
    persisted verification only when the live readback is unavailable; a new
    pending Intelligent hold always requires a live physical readback. A
    bounded source-uncertainty grace may retain an already-verified confirmed
    hold without becoming new cheap-period authority.
    """
    if latched_min_soc_percent is None:
        return False
    try:
        floor = float(latched_min_soc_percent)
    except (TypeError, ValueError):
        return False
    if not 0.0 <= floor <= 100.0:
        return False

    observed = observed_min_soc_on_grid_percent
    verified = last_verified_min_soc_on_grid_percent
    try:
        observed_value = float(observed) if observed is not None else None
    except (TypeError, ValueError):
        observed_value = None
    try:
        verified_value = float(verified) if verified is not None else None
    except (TypeError, ValueError):
        verified_value = None

    live_hold_verified = observed_value is not None and observed_value + 0.05 >= floor
    physical_hold_verified = live_hold_verified or (
        not pending_intelligent_ev_hold_active
        and observed_value is None
        and verified_value is not None
        and verified_value + 0.05 >= floor
    )
    return bool(
        owned_by_kems
        and last_applied_action == "self_use"
        and physical_hold_verified
        and (
            cheap_period_confirmed
            or source_uncertainty_grace_active
            or pending_intelligent_ev_hold_active
        )
        and no_paid_export_mode
        and ev_connected is not False
        and operating_mode == "control"
        and master_control_enabled
        and user_commissioned
        and not emergency_stop
        and not island_mode_active
        and grid_available
    )


def assess_foxess_control_write_authority(
    control: ControlState,
    *,
    technical_ready: bool,
    binding_ready: bool,
    reviewed_version_matches: bool,
    no_paid_export_mode: bool,
    cheap_period_confirmed: bool,
    user_commissioned: bool,
    master_control_enabled: bool,
    emergency_stop: bool,
    export_tariff_ready: bool = True,
    effective_export_limit_kw: float = 0.0,
    paid_export_commissioned: bool = False,
    paid_export_stage_limit_kw: float = 1.0,
    paid_export_commissioning_fault: str | None = None,
) -> FoxESSControlDecision:
    """Return the bounded hardware action for the reviewed FoxESS surface.

    No-paid-export retains the established Self Use / confirmed-cheap Force
    Charge contract. Paid export adds one fail-closed Force Discharge path:
    the economic planner must explicitly request grid export, the tariff must be
    ready, the export ceiling must be positive, and the first physical export is
    staged to a small commissioning limit until telemetry proves direction and
    bounded grid feed-in.
    """
    backend_available = bool(binding_ready and reviewed_version_matches)

    def blocked(reason: str, *, action: str = "release") -> FoxESSControlDecision:
        return FoxESSControlDecision(
            backend_available=backend_available,
            commands_permitted=False,
            action=action if backend_available else "none",
            reason=reason,
            min_soc_on_grid_percent=round(control.desired_min_soc_percent, 1),
        )

    if not reviewed_version_matches:
        return blocked("FoxESS Modbus version is outside the reviewed control contract")
    if not binding_ready:
        return blocked("Reviewed FoxESS command entities are not uniquely bound")
    if emergency_stop or control.operating_reason == "emergency_stop":
        return blocked("KEMS emergency stop is active")
    if control.operating_mode != "control":
        return blocked("KEMS is not in Control mode")
    if not master_control_enabled:
        return blocked("Master control enable is off")
    if not user_commissioned:
        return blocked("User commissioning acknowledgement is off")
    if not technical_ready:
        return blocked("Control-critical commissioning evidence is not ready")
    if not control.data_fresh or not control.plan_safe:
        return blocked("Current KEMS control plan is not fresh and safe")
    if (
        control.preflight_total <= 0
        or control.preflight_passed != control.preflight_total
    ):
        return blocked("KEMS preflight suite is not fully passing")
    if control.island_mode_active or not control.grid_available:
        return blocked(
            "Grid unavailable/island mode is owned by local inverter protection"
        )

    if control.alpha969_routing_shadow_only or control.operating_reason.startswith(
        ("no_export_overnight", "no_export_extra_slot")
    ):
        return blocked(
            "Alpha9.69 no-export routing is shadow-only pending physical "
            "shared-bus EV/grid allocation and below-floor Force Charge validation"
        )

    min_soc = round(control.desired_min_soc_percent, 1)
    desired_export = max(float(control.desired_battery_export_power_kw), 0.0)

    if no_paid_export_mode:
        if control.desired_grid_export_allowed or desired_export > _EPSILON_KW:
            return blocked(
                "Deliberate battery/grid export is outside No paid export authority"
            )
    else:
        if not export_tariff_ready:
            return blocked("Paid export tariff data is not ready")
        if paid_export_commissioning_fault:
            return blocked(
                "Paid export commissioning is latched fail-closed: "
                f"{paid_export_commissioning_fault}"
            )
        if desired_export > _EPSILON_KW and not control.desired_grid_export_allowed:
            return blocked(
                "Contradictory paid-export plan requests battery export while "
                "grid export is disabled"
            )
        if desired_export > _EPSILON_KW:
            if cheap_period_confirmed:
                return blocked(
                    "Deliberate paid export is blocked during a confirmed cheap period"
                )
            limit_kw = max(float(effective_export_limit_kw), 0.0)
            if limit_kw <= _EPSILON_KW:
                return blocked("Effective paid-export ceiling is zero")
            requested_kw = min(desired_export, limit_kw)
            staged = not paid_export_commissioned
            if staged:
                requested_kw = min(
                    requested_kw,
                    max(float(paid_export_stage_limit_kw), 0.0),
                )
            if requested_kw <= _EPSILON_KW:
                return blocked("Paid export commissioning stage limit is zero")
            return FoxESSControlDecision(
                backend_available=True,
                commands_permitted=True,
                action="force_discharge",
                reason=(
                    "Paid export is inside the bounded live scope"
                    if not staged
                    else (
                        "Paid export is limited to the Alpha9.82 physical "
                        "commissioning stage"
                    )
                ),
                force_discharge_power_kw=round(requested_kw, 3),
                export_power_limit_w=round(limit_kw * 1000.0),
                export_commissioning_stage_limited=staged,
                min_soc_on_grid_percent=min_soc,
            )

    if control.desired_work_mode == "Force Charge":
        if not cheap_period_confirmed:
            return blocked("Force Charge is not backed by a confirmed cheap period")
        if control.desired_charge_power_kw <= _EPSILON_KW:
            return FoxESSControlDecision(
                backend_available=True,
                commands_permitted=True,
                action="self_use",
                reason="Cheap-period charge target is already satisfied",
                min_soc_on_grid_percent=min_soc,
            )
        return FoxESSControlDecision(
            backend_available=True,
            commands_permitted=True,
            action="force_charge",
            reason="Confirmed cheap-period charging is inside the bounded live scope",
            force_charge_power_kw=round(control.desired_charge_power_kw, 3),
            min_soc_on_grid_percent=min_soc,
        )

    if control.desired_work_mode in {"Self Use", "Feed-in First"}:
        return FoxESSControlDecision(
            backend_available=True,
            commands_permitted=True,
            action="self_use",
            reason=(
                "No-paid-export Self Use is inside the bounded live scope"
                if no_paid_export_mode
                else "Paid-export idle/house-support Self Use is inside the bounded live scope"
            ),
            min_soc_on_grid_percent=min_soc,
        )

    if control.desired_work_mode in {"No change", "Stop KEMS writes"}:
        return blocked("Planner requested no hardware command")

    return blocked(
        f"Work mode {control.desired_work_mode!r} is outside the current live scope"
    )
