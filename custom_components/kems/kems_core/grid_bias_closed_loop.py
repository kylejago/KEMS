"""Pure bounded closed-loop grid-bias controller for Alpha9.62."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import ControlState

GRID_BIAS_DEADBAND_W = 5.0
GRID_BIAS_MAX_ADJUSTMENT_W = 25.0
GRID_BIAS_MAX_COMMAND_W = 100.0
GRID_BIAS_MAX_COMMAND_KW = GRID_BIAS_MAX_COMMAND_W / 1000.0
_EPSILON_KW = 0.001


@dataclass(frozen=True, slots=True)
class GridBiasControlStep:
    """One deterministic grid-zero correction step."""

    active: bool
    reason: str
    observed_grid_power_w: float | None
    target_grid_power_w: float
    error_w: float | None
    previous_setpoint_kw: float
    requested_setpoint_kw: float
    correction_w: float
    within_deadband: bool
    saturated: bool

    def to_dict(self) -> dict[str, object]:
        """Return a diagnostics-safe payload."""
        return asdict(self)


def next_grid_bias_control_step(
    control: ControlState,
    previous_setpoint_kw: float,
) -> GridBiasControlStep:
    """Return the next KEMS-owned Force Discharge trim setpoint.

    The configured bias is the desired grid target, not permission for economic
    export. Entry always starts at the configured bias itself. Only after KEMS
    owns that remote-control setpoint may it correct residual tracking error,
    with a 5 W deadband, a 25 W-per-scan rate limit and a hard 100 W ceiling.
    """

    previous_w = min(
        max(float(previous_setpoint_kw), 0.0) * 1000.0,
        GRID_BIAS_MAX_COMMAND_W,
    )
    target_w = float(control.grid_import_prevention_target_grid_power_w)
    observed = control.grid_import_prevention_observed_grid_power_w

    requested = bool(
        control.grid_import_prevention_bias_active
        and control.desired_grid_bias_export_power_kw > _EPSILON_KW
        and control.grid_import_prevention_bias_w > 0.0
    )
    if not requested:
        return GridBiasControlStep(
            active=False,
            reason="bias_not_requested",
            observed_grid_power_w=observed,
            target_grid_power_w=target_w,
            error_w=None,
            previous_setpoint_kw=round(previous_w / 1000.0, 3),
            requested_setpoint_kw=0.0,
            correction_w=round(-previous_w, 1),
            within_deadband=False,
            saturated=False,
        )
    if observed is None:
        return GridBiasControlStep(
            active=False,
            reason="grid_power_unavailable",
            observed_grid_power_w=None,
            target_grid_power_w=target_w,
            error_w=None,
            previous_setpoint_kw=round(previous_w / 1000.0, 3),
            requested_setpoint_kw=0.0,
            correction_w=round(-previous_w, 1),
            within_deadband=False,
            saturated=False,
        )
    if target_w >= 0.0:
        return GridBiasControlStep(
            active=False,
            reason="grid_bias_target_is_not_export_side",
            observed_grid_power_w=float(observed),
            target_grid_power_w=target_w,
            error_w=None,
            previous_setpoint_kw=round(previous_w / 1000.0, 3),
            requested_setpoint_kw=0.0,
            correction_w=round(-previous_w, 1),
            within_deadband=False,
            saturated=False,
        )

    observed_w = float(observed)
    error_w = observed_w - target_w

    # Do not jump straight from Self Use to an error-derived value. The first
    # remote-control command is always just the configured tiny export bias.
    if previous_w <= 0.5:
        if error_w <= GRID_BIAS_DEADBAND_W:
            return GridBiasControlStep(
                active=False,
                reason="self_use_already_at_or_below_bias_target",
                observed_grid_power_w=round(observed_w, 1),
                target_grid_power_w=round(target_w, 1),
                error_w=round(error_w, 1),
                previous_setpoint_kw=0.0,
                requested_setpoint_kw=0.0,
                correction_w=0.0,
                within_deadband=abs(error_w) <= GRID_BIAS_DEADBAND_W,
                saturated=False,
            )
        entry_w = min(
            max(float(control.grid_import_prevention_bias_w), 1.0),
            GRID_BIAS_MAX_COMMAND_W,
        )
        return GridBiasControlStep(
            active=True,
            reason="enter_bounded_grid_bias",
            observed_grid_power_w=round(observed_w, 1),
            target_grid_power_w=round(target_w, 1),
            error_w=round(error_w, 1),
            previous_setpoint_kw=0.0,
            requested_setpoint_kw=round(entry_w / 1000.0, 3),
            correction_w=round(entry_w, 1),
            within_deadband=False,
            saturated=entry_w >= GRID_BIAS_MAX_COMMAND_W,
        )

    if abs(error_w) <= GRID_BIAS_DEADBAND_W:
        return GridBiasControlStep(
            active=True,
            reason="hold_within_deadband",
            observed_grid_power_w=round(observed_w, 1),
            target_grid_power_w=round(target_w, 1),
            error_w=round(error_w, 1),
            previous_setpoint_kw=round(previous_w / 1000.0, 3),
            requested_setpoint_kw=round(previous_w / 1000.0, 3),
            correction_w=0.0,
            within_deadband=True,
            saturated=previous_w >= GRID_BIAS_MAX_COMMAND_W,
        )

    correction_w = min(
        max(error_w, -GRID_BIAS_MAX_ADJUSTMENT_W),
        GRID_BIAS_MAX_ADJUSTMENT_W,
    )
    unclamped_w = previous_w + correction_w
    next_w = min(max(unclamped_w, 0.0), GRID_BIAS_MAX_COMMAND_W)
    if next_w <= 0.5:
        next_w = 0.0
    saturated = abs(next_w - unclamped_w) > 0.1

    return GridBiasControlStep(
        active=next_w > 0.0,
        reason=(
            "increase_bounded_grid_bias"
            if next_w > previous_w
            else "decrease_bounded_grid_bias"
            if next_w < previous_w
            else "grid_bias_saturated"
        ),
        observed_grid_power_w=round(observed_w, 1),
        target_grid_power_w=round(target_w, 1),
        error_w=round(error_w, 1),
        previous_setpoint_kw=round(previous_w / 1000.0, 3),
        requested_setpoint_kw=round(next_w / 1000.0, 3),
        correction_w=round(next_w - previous_w, 1),
        within_deadband=False,
        saturated=saturated or next_w >= GRID_BIAS_MAX_COMMAND_W,
    )
