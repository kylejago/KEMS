"""Home Assistant-independent helpers for fast control refresh inputs."""

from __future__ import annotations


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
