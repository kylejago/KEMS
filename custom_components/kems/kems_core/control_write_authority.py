"""Pure authority gate for bounded FoxESS control, including Alpha9.63 grid trim."""

from __future__ import annotations

from dataclasses import dataclass

from .grid_import_prevention import (
    GRID_BIAS_MAX_CORRECTION_KW,
    grid_bias_required_correction_kw,
)
from .models import ControlState

_EPSILON_KW = 0.001
_GRID_BIAS_ENTER_IMPORT_W = 5.0
_GRID_BIAS_EXIT_EXPORT_W = -50.0
_GRID_BIAS_ERROR_DEADBAND_W = 5.0
_GRID_BIAS_MAX_STEP_KW = 0.050


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

    Alpha9.63 retains the tightly bounded Force Discharge exception for the
    optional near-zero grid-import trim, but closes the loop on measured grid
    power. The correction follows observed minus target grid power, is clamped
    by planner headroom, rate-limited here and held through a small deadband.
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
        if bias_shadow_only:
            observed_grid_w = control.grid_import_prevention_observed_grid_power_w
            if grid_bias_force_discharge_ready and observed_grid_w is not None:
                should_engage = (
                    float(observed_grid_w) > _GRID_BIAS_EXIT_EXPORT_W
                    if grid_bias_engaged
                    else float(observed_grid_w) >= _GRID_BIAS_ENTER_IMPORT_W
                )
                if should_engage:
                    target_grid_w = float(
                        control.grid_import_prevention_target_grid_power_w
                    )
                    error_w = float(observed_grid_w) - target_grid_w
                    requested_correction_kw = grid_bias_required_correction_kw(
                        float(observed_grid_w),
                        target_grid_w,
                    )
                    previous_correction_kw = (
                        min(
                            max(float(grid_bias_previous_correction_kw), 0.0),
                            GRID_BIAS_MAX_CORRECTION_KW,
                        )
                        if grid_bias_engaged
                        else 0.0
                    )
                    if (
                        grid_bias_engaged
                        and abs(error_w) <= _GRID_BIAS_ERROR_DEADBAND_W
                    ):
                        applied_correction_kw = previous_correction_kw
                    else:
                        lower = max(
                            previous_correction_kw - _GRID_BIAS_MAX_STEP_KW,
                            0.0,
                        )
                        upper = previous_correction_kw + _GRID_BIAS_MAX_STEP_KW
                        applied_correction_kw = min(
                            max(requested_correction_kw, lower),
                            upper,
                        )

                    base_output_kw = max(float(control.total_kh7_ac_output_kw), 0.0)
                    discharge_headroom_kw = max(
                        float(max_discharge_kw)
                        - max(float(control.desired_total_discharge_power_kw), 0.0),
                        0.0,
                    )
                    inverter_headroom_kw = max(
                        float(inverter_limit_kw) - base_output_kw,
                        0.0,
                    )
                    applied_correction_kw = min(
                        applied_correction_kw,
                        discharge_headroom_kw,
                        inverter_headroom_kw,
                        max(float(export_limit_kw), 0.0),
                        GRID_BIAS_MAX_CORRECTION_KW,
                    )
                    total_output_kw = base_output_kw + applied_correction_kw
                    actual_correction_kw = applied_correction_kw
                    if total_output_kw > _EPSILON_KW:
                        return FoxESSControlDecision(
                            backend_available=True,
                            commands_permitted=True,
                            action="grid_bias_force_discharge",
                            reason=(
                                "Bounded closed-loop grid-import prevention trim is "
                                "active; economic export authority remains disabled"
                            ),
                            force_discharge_power_kw=round(total_output_kw, 3),
                            min_soc_on_grid_percent=min_soc,
                            grid_bias_live=True,
                            grid_bias_shadow_only=False,
                            grid_bias_error_w=round(error_w, 1),
                            grid_bias_requested_correction_kw=round(
                                requested_correction_kw,
                                3,
                            ),
                            grid_bias_applied_correction_kw=round(
                                actual_correction_kw,
                                3,
                            ),
                        )
                return FoxESSControlDecision(
                    backend_available=True,
                    commands_permitted=True,
                    action="self_use",
                    reason=(
                        "Grid-import prevention trim is not engaged because "
                        "natural grid flow is already beyond the live hysteresis target"
                    ),
                    min_soc_on_grid_percent=min_soc,
                    grid_bias_live=False,
                    grid_bias_shadow_only=False,
                )

        return FoxESSControlDecision(
            backend_available=True,
            commands_permitted=True,
            action="self_use",
            reason=(
                "No-paid-export Self Use is inside the bounded control scope"
                if not bias_shadow_only
                else (
                    "Self Use permitted; grid-import prevention remains Shadow-only "
                    "because the reviewed Force Discharge command is unavailable"
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
