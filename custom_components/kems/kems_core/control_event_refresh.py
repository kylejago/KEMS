"""Home Assistant-independent helpers for fast control refresh inputs."""

from __future__ import annotations

import math

_UNUSABLE_CONTROL_STATES = {"unknown", "unavailable"}


def control_source_state_uncertain(state: str | None) -> bool:
    """Return whether one discrete authority source is temporarily unusable."""
    if state is None:
        return True
    return str(state).strip().lower() in _UNUSABLE_CONTROL_STATES


def critical_control_refresh_entity_ids(
    *entity_ids: str | None,
) -> tuple[str, ...]:
    """Return de-duplicated low-frequency control-authority source IDs."""
    return tuple(dict.fromkeys(entity_id for entity_id in entity_ids if entity_id))


def meaningful_control_state_transition(
    old_state: str | None,
    new_state: str | None,
) -> bool:
    """Return whether a discrete control source changed to a new usable state."""
    return old_state is not None and new_state is not None and old_state != new_state


def _ev_power_band(state: str | None, *, threshold_kw: float) -> int:
    """-1 unknown, 0 confidently idle, 1 drawing EV charging power."""
    if state is None:
        return -1
    try:
        watts = float(state)
    except (TypeError, ValueError):
        return -1
    if not math.isfinite(watts) or watts < 0.0:
        return -1
    return 1 if watts > threshold_kw else 0


def meaningful_ev_power_transition(
    old_state: str | None,
    new_state: str | None,
    *,
    charging_threshold_kw: float = 0.1,
) -> bool:
    """Request prompt control when Ohme starts/stops drawing or goes stale.

    Do not schedule full KEMS planning on every change in charger power.
    The normal cadence still observes steady-state charging.
    """
    if old_state is None or new_state is None:
        return False
    return _ev_power_band(
        old_state, threshold_kw=charging_threshold_kw
    ) != _ev_power_band(new_state, threshold_kw=charging_threshold_kw)
