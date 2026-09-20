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
        return blocked("Deliberate battery/grid export is outside the current live scope")

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
