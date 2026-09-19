"""Pure authority gate for bounded FoxESS control, including Alpha9.65 fixed bias."""

from __future__ import annotations

from dataclasses import dataclass

from .grid_import_prevention import FIXED_GRID_BIAS_KW
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
    min_soc_on_grid_percent: float | None = None
    grid_bias_live: bool = False
    grid_bias_shadow_only: bool = False
    grid_bias_error_w: float | None = None
    grid_bias_requested_correction_kw: float = 0.0
    grid_bias_applied_correction_kw: float = 0.0


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
    grid_bias_force_discharge_ready: bool = False,
    grid_bias_engaged: bool = False,
    grid_bias_previous_correction_kw: float = 0.0,
    inverter_limit_kw: float = 7.0,
    max_discharge_kw: float = 7.0,
    export_limit_kw: float = 7.0,
) -> FoxESSControlDecision:
    """Return the narrow non-Agile hardware action.

    Alpha9.65 removes measured-grid-error feedback. The optional daytime
    anti-import path is a deterministic fixed 50 W export bias added to the
    already-bounded KH7 house-support output. Deliberate/economic export is a
    separate, higher-priority authority and is never stacked with this bias.
    """
    backend_available = bool(binding_ready and reviewed_version_matches)
    bias_shadow_only = bool(
        control.grid_import_prevention_bias_active
        and (
            control.grid_import_prevention_bias_w > 0.0
            or control.desired_grid_bias_export_power_kw > _EPSILON_KW
        )
    )

    def blocked(reason: str, *, action: str = "release") -> FoxESSControlDecision:
        return FoxESSControlDecision(
            backend_available=backend_available,
            commands_permitted=False,
            action=action if backend_available else "none",
            reason=reason,
            min_soc_on_grid_percent=round(control.desired_min_soc_percent, 1),
            grid_bias_shadow_only=bias_shadow_only,
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
        return blocked("Paid/Agile export control is outside the Alpha9.56 scope")
    if (
        control.desired_grid_export_allowed
        or control.desired_battery_export_power_kw > _EPSILON_KW
    ):
        return blocked("Deliberate battery/grid export is outside the Alpha9.56 scope")

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
                grid_bias_shadow_only=bias_shadow_only,
            )
        return FoxESSControlDecision(
            backend_available=True,
            commands_permitted=True,
            action="force_charge",
            reason="Confirmed cheap-period charging is inside the Alpha9.56 scope",
            force_charge_power_kw=round(control.desired_charge_power_kw, 3),
            min_soc_on_grid_percent=min_soc,
            grid_bias_shadow_only=bias_shadow_only,
        )

    if control.desired_work_mode in {"Self Use", "Feed-in First"}:
        if bias_shadow_only and grid_bias_force_discharge_ready:
            base_output_kw = max(float(control.total_kh7_ac_output_kw), 0.0)
            fixed_bias_kw = min(
                max(float(control.desired_grid_bias_export_power_kw), 0.0),
                FIXED_GRID_BIAS_KW,
            )
            discharge_headroom_kw = max(
                float(max_discharge_kw)
                - max(float(control.desired_total_discharge_power_kw), 0.0),
                0.0,
            )
            inverter_headroom_kw = max(
                float(inverter_limit_kw) - base_output_kw,
                0.0,
            )
            applied_bias_kw = min(
                fixed_bias_kw,
                discharge_headroom_kw,
                inverter_headroom_kw,
                max(float(export_limit_kw), 0.0),
            )
            total_output_kw = base_output_kw + applied_bias_kw
            if (
                applied_bias_kw >= FIXED_GRID_BIAS_KW - 1e-9
                and total_output_kw > _EPSILON_KW
            ):
                return FoxESSControlDecision(
                    backend_available=True,
                    commands_permitted=True,
                    action="grid_bias_force_discharge",
                    reason=(
                        "Fixed 50 W grid-import-prevention export bias is active; "
                        "economic export authority remains separate and higher priority"
                    ),
                    force_discharge_power_kw=round(total_output_kw, 3),
                    min_soc_on_grid_percent=min_soc,
                    grid_bias_live=True,
                    grid_bias_shadow_only=False,
                    grid_bias_requested_correction_kw=round(FIXED_GRID_BIAS_KW, 3),
                    grid_bias_applied_correction_kw=round(applied_bias_kw, 3),
                )

        return FoxESSControlDecision(
            backend_available=True,
            commands_permitted=True,
            action="self_use",
            reason=(
                "No-paid-export Self Use is inside the bounded control scope"
                if not bias_shadow_only
                else (
                    "Self Use permitted; fixed 50 W grid-import-prevention bias "
                    "cannot be applied on the reviewed Force Discharge surface"
                )
            ),
            min_soc_on_grid_percent=min_soc,
            grid_bias_shadow_only=bias_shadow_only,
        )

    if control.desired_work_mode in {"No change", "Stop KEMS writes"}:
        return blocked("Planner requested no hardware command")

    return blocked(
        f"Work mode {control.desired_work_mode!r} is outside the Alpha9.56 scope"
    )
