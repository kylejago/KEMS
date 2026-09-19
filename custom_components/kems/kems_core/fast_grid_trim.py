"""Pure fast-loop maths for Alpha9.64 FoxESS grid trim."""

from __future__ import annotations

from dataclasses import dataclass

FAST_GRID_TRIM_POLL_SECONDS = 5
FAST_GRID_TRIM_MAX_STEP_KW = 0.050
FAST_GRID_TRIM_ENVELOPE_KW = 0.100
FAST_GRID_TRIM_DEADBAND_W = 5.0


@dataclass(frozen=True, slots=True)
class FastGridTrimResult:
    """One bounded correction for a fresh FoxESS grid sample."""

    observed_grid_w: float
    target_grid_w: float
    error_w: float
    current_force_discharge_kw: float
    target_force_discharge_kw: float
    delta_kw: float
    envelope_min_kw: float
    envelope_max_kw: float
    changed: bool
    reason: str


def calculate_fast_grid_trim(
    *,
    current_force_discharge_kw: float,
    observed_grid_w: float,
    target_grid_w: float,
    planner_base_output_kw: float,
    inverter_limit_kw: float,
    max_discharge_kw: float,
    planner_discharge_kw: float,
    export_limit_kw: float,
) -> FastGridTrimResult:
    """Return a signed, slew-limited correction around the latest planner base.

    The fast loop never invents a new control mode. It only nudges an already
    authorised Force Discharge total-output setpoint using a fresh grid sample.
    """
    current_kw = max(float(current_force_discharge_kw), 0.0)
    base_kw = max(float(planner_base_output_kw), 0.0)
    observed_w = float(observed_grid_w)
    target_w = float(target_grid_w)
    error_w = observed_w - target_w

    correction_envelope_kw = min(
        FAST_GRID_TRIM_ENVELOPE_KW,
        max(float(export_limit_kw), 0.0),
    )
    discharge_headroom_kw = max(
        float(max_discharge_kw) - max(float(planner_discharge_kw), 0.0),
        0.0,
    )
    upper_extra_kw = min(correction_envelope_kw, discharge_headroom_kw)
    envelope_min_kw = max(base_kw - correction_envelope_kw, 0.0)
    envelope_max_kw = min(
        base_kw + upper_extra_kw,
        max(float(inverter_limit_kw), 0.0),
    )
    envelope_min_kw = min(envelope_min_kw, envelope_max_kw)

    if abs(error_w) <= FAST_GRID_TRIM_DEADBAND_W:
        target_kw = min(max(current_kw, envelope_min_kw), envelope_max_kw)
        return FastGridTrimResult(
            observed_grid_w=round(observed_w, 1),
            target_grid_w=round(target_w, 1),
            error_w=round(error_w, 1),
            current_force_discharge_kw=round(current_kw, 3),
            target_force_discharge_kw=round(target_kw, 3),
            delta_kw=round(target_kw - current_kw, 3),
            envelope_min_kw=round(envelope_min_kw, 3),
            envelope_max_kw=round(envelope_max_kw, 3),
            changed=abs(target_kw - current_kw) > 0.0005,
            reason="inside_5w_deadband",
        )

    requested_delta_kw = error_w / 1000.0
    bounded_delta_kw = min(
        max(requested_delta_kw, -FAST_GRID_TRIM_MAX_STEP_KW),
        FAST_GRID_TRIM_MAX_STEP_KW,
    )
    target_kw = min(
        max(current_kw + bounded_delta_kw, envelope_min_kw),
        envelope_max_kw,
    )
    return FastGridTrimResult(
        observed_grid_w=round(observed_w, 1),
        target_grid_w=round(target_w, 1),
        error_w=round(error_w, 1),
        current_force_discharge_kw=round(current_kw, 3),
        target_force_discharge_kw=round(target_kw, 3),
        delta_kw=round(target_kw - current_kw, 3),
        envelope_min_kw=round(envelope_min_kw, 3),
        envelope_max_kw=round(envelope_max_kw, 3),
        changed=abs(target_kw - current_kw) > 0.0005,
        reason="bounded_signed_grid_error",
    )
