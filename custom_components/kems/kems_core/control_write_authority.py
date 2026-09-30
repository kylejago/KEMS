"""Pure authority gate for bounded non-Agile FoxESS control."""

from __future__ import annotations

from dataclasses import dataclass

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
    min_soc_on_grid_percent: float | None = None


def resolve_live_min_soc_on_grid(
    decision: FoxESSControlDecision,
    *,
    cheap_period_confirmed: bool,
    previous_min_soc_on_grid: float | None,
) -> float | None:
    """Return the physically safe MinSOC target for the reviewed live write.

    The normal KEMS reserve is a planning/discharge target, not permission to
    buy daytime grid energy. Outside a confirmed cheap period, Self Use keeps
    the pre-KEMS MinSOC-on-grid baseline instead of raising it to the planner
    reserve. Confirmed-cheap Self Use/Force Charge paths retain their requested
    MinSOC, including the Alpha9.70 EV battery-hold floor.
    """
    requested = decision.min_soc_on_grid_percent
    if cheap_period_confirmed or decision.action != "self_use":
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
) -> bool:
    """Return whether an already-applied cheap-window EV hold must be frozen.

    Freeze means *no new FoxESS writes*. It preserves only a physically
    verified KEMS-owned Self Use + MinSOC state through transient telemetry or
    commissioning-readiness loss. A fresh readback below the latched floor
    always blocks freeze; only an unavailable readback may fall back to the
    last persisted verification. A bounded source-uncertainty grace may retain
    that already-verified hold without becoming new cheap-period authority.
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

    physical_hold_verified = (
        observed_value is not None and observed_value + 0.05 >= floor
    ) or (
        observed_value is None
        and verified_value is not None
        and verified_value + 0.05 >= floor
    )
    return bool(
        owned_by_kems
        and last_applied_action == "self_use"
        and physical_hold_verified
        and (cheap_period_confirmed or source_uncertainty_grace_active)
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
) -> FoxESSControlDecision:
    """Return the narrow non-Agile hardware action.

    Outside a confirmed cheap period the only normal grid-connected action is
    Self Use. Confirmed cheap periods may use Force Charge. Deliberate/economic
    Force Discharge, Agile/paid-export control and import/export power-limit
    writes remain outside this authority.
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
    if not no_paid_export_mode:
        return blocked("Paid/Agile export control is outside the current live scope")
    if (
        control.desired_grid_export_allowed
        or control.desired_battery_export_power_kw > _EPSILON_KW
    ):
        return blocked(
            "Deliberate battery/grid export is outside the current live scope"
        )

    # Alpha9.69 introduces new SOC-floor and EV/load routing semantics. The
    # old Alpha9.67 live contract never validated their physical KH7 behaviour.
    # The sticky flag survives dataclasses.replace overlays (e.g. Happy Hour
    # replacing operating_reason); the reason check is defence in depth.
    if control.alpha969_routing_shadow_only or control.operating_reason.startswith(
        ("no_export_overnight", "no_export_extra_slot")
    ):
        return blocked(
            "Alpha9.69 no-export routing is shadow-only pending physical "
            "shared-bus EV/grid allocation and below-floor Force Charge validation"
        )

    min_soc = round(control.desired_min_soc_percent, 1)
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
            reason="No-paid-export Self Use is inside the bounded live scope",
            min_soc_on_grid_percent=min_soc,
        )

    if control.desired_work_mode in {"No change", "Stop KEMS writes"}:
        return blocked("Planner requested no hardware command")

    return blocked(
        f"Work mode {control.desired_work_mode!r} is outside the current live scope"
    )
