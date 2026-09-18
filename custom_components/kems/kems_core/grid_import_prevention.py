"""Shadow-only grid zero-point bias for avoiding tiny standing imports."""

from __future__ import annotations

from dataclasses import replace

from .models import ControlConfig, ControlState, Snapshot

_GRID_TRIM_WINDOW_KW = 0.100
_EPSILON_KW = 0.001


def apply_grid_import_prevention_bias(
    control: ControlState,
    snapshot: Snapshot,
    config: ControlConfig,
) -> ControlState:
    """Apply a tiny, separately-accounted grid-export bias when safe.

    This is not economic battery export. It represents a user-selected
    near-zero-grid operating offset so a future commissioned backend can target
    a few watts of export instead of allowing a few watts of standing import.
    Alpha9.55 remains Shadow-only and never writes this request to hardware.
    """
    configured_w = min(
        max(float(config.grid_import_prevention_bias_w), 0.0),
        100.0,
    )
    bias_kw = configured_w / 1000.0
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
    if configured_w <= 0:
        reason = "disabled"
    elif config.emergency_stop or control.operating_reason == "emergency_stop":
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
        reason = "deliberate_export"
    elif bias_kw > config.export_limit_kw + 1e-9:
        reason = "kems_export_ceiling_below_bias"
    elif battery_soc is None:
        reason = "battery_soc_unavailable"
    elif float(battery_soc) <= reserve_percent + 1e-6:
        reason = "battery_at_or_below_reserve"
    elif abs(observed_grid_kw) > _GRID_TRIM_WINDOW_KW + 1e-9:
        reason = "grid_exchange_outside_trim_window"
    elif control.total_kh7_ac_output_kw + bias_kw > config.inverter_limit_kw + 1e-9:
        reason = "inverter_headroom_below_bias"
    elif (
        control.desired_total_discharge_power_kw + bias_kw
        > config.max_discharge_kw + 1e-9
    ):
        reason = "battery_discharge_headroom_below_bias"

    active = reason is None
    requested_bias_kw = bias_kw if active else 0.0
    return replace(
        control,
        desired_grid_bias_export_power_kw=round(requested_bias_kw, 3),
        grid_import_prevention_bias_w=round(configured_w, 1),
        grid_import_prevention_bias_active=active,
        grid_import_prevention_target_grid_power_w=round(-configured_w, 1),
        grid_import_prevention_observed_grid_power_w=observed_grid_w,
        grid_import_prevention_bias_suppressed_reason=reason,
    )
