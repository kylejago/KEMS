"""Fixed daytime export bias for avoiding standing grid import."""

from __future__ import annotations

from dataclasses import replace

from .models import ControlConfig, ControlState, Snapshot

FIXED_GRID_BIAS_W = 50.0
FIXED_GRID_BIAS_KW = FIXED_GRID_BIAS_W / 1000.0
_EPSILON_KW = 0.001


def apply_grid_import_prevention_bias(
    control: ControlState,
    snapshot: Snapshot,
    config: ControlConfig,
) -> ControlState:
    """Apply the fixed 50 W non-economic export bias when safe.

    Alpha9.65 deliberately removes measured-grid-error tracking. Outside a
    confirmed cheap period, KEMS requests its normal house-support KH7 output
    plus a fixed 50 W export allowance. This bias is lower priority than any
    deliberate/economic export request, so future Agile export authority
    supersedes it rather than stacking with it.
    """
    configured_w = FIXED_GRID_BIAS_W
    bias_kw = FIXED_GRID_BIAS_KW
    target_grid_w = -FIXED_GRID_BIAS_W
    grid_import_kw = max(float(snapshot.grid_import_kw or 0.0), 0.0)
    grid_export_kw = max(float(snapshot.grid_export_kw or 0.0), 0.0)
    observed_grid_kw = grid_import_kw - grid_export_kw
    observed_grid_w = round(observed_grid_kw * 1000.0, 1)
    reserve_percent = max(
        float(config.normal_reserve_percent),
        float(control.desired_min_soc_percent),
    )
    battery_soc = snapshot.battery_soc

    reason: str | None = None
    if config.emergency_stop or control.operating_reason == "emergency_stop":
        reason = "emergency_stop"
    elif control.operating_mode == "observe" or control.desired_work_mode in {
        "No change",
        "Stop KEMS writes",
    }:
        reason = "operating_mode_does_not_request_control"
    elif not control.data_fresh or not control.plan_safe:
        reason = "control_plan_not_safe"
    elif control.island_mode_active or not control.grid_available:
        reason = "island_or_grid_unavailable"
    elif snapshot.cheap_period_confirmed:
        reason = "cheap_period"
    elif control.desired_charge_power_kw > _EPSILON_KW:
        reason = "deliberate_charge"
    elif control.desired_battery_export_power_kw > _EPSILON_KW:
        # Deliberate/Agile export is always higher authority than the standing
        # 50 W anti-import bias. Never stack the two export intents.
        reason = "deliberate_export_has_priority"
    elif bias_kw > config.export_limit_kw + 1e-9:
        reason = "kems_export_ceiling_below_fixed_bias"
    elif battery_soc is None:
        reason = "battery_soc_unavailable"
    elif float(battery_soc) <= reserve_percent + 1e-6:
        reason = "battery_at_or_below_reserve"
    elif control.total_kh7_ac_output_kw + bias_kw > config.inverter_limit_kw + 1e-9:
        reason = "inverter_headroom_below_fixed_bias"
    elif (
        control.desired_total_discharge_power_kw + bias_kw
        > config.max_discharge_kw + 1e-9
    ):
        reason = "battery_discharge_headroom_below_fixed_bias"

    active = reason is None
    requested_bias_kw = bias_kw if active else 0.0
    return replace(
        control,
        desired_grid_bias_export_power_kw=round(requested_bias_kw, 3),
        grid_import_prevention_bias_w=FIXED_GRID_BIAS_W,
        grid_import_prevention_bias_active=active,
        grid_import_prevention_target_grid_power_w=target_grid_w,
        grid_import_prevention_observed_grid_power_w=observed_grid_w,
        grid_import_prevention_bias_suppressed_reason=reason,
    )
