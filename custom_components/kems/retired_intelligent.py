"""One-way retirement of KEMS-owned, unsupported Intelligent UI surfaces.

The external Octopus Intelligent integration and its entities are never changed.
Only KEMS's own orphaned binary sensors are pruned, and only when they are
currently unavailable or unknown. This module has no tariff/control authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_RETIRED_OPTION = "intelligent_slots_enabled"
_RETIRED_BINARY_SENSOR_KEYS = (
    "intelligent_slot",
    "intelligent_slot_source_fresh",
)


def without_retired_intelligent_option(options: Mapping[str, Any]) -> dict[str, Any]:
    """Never re-persist the legacy daytime-discount opt-in on any write path."""
    clean = dict(options)
    clean.pop(_RETIRED_OPTION, None)
    return clean


def retire_unavailable_kems_intelligent_entities(
    registry: Any,
    states: Any,
    *,
    entry_id: str,
) -> tuple[str, ...]:
    """Remove only this entry's confirmed orphaned, unavailable KEMS entities.

    The registry unique-ID/platform/config-entry guards prevent touching any
    external Octopus entities or a renamed/unrelated Home Assistant entity.
    A live or independently reactivated sensor is left intact for review.
    """
    removed: list[str] = []
    for key in _RETIRED_BINARY_SENSOR_KEYS:
        unique_id = f"{entry_id}_{key}"
        entity_id = registry.async_get_entity_id("binary_sensor", "kems", unique_id)
        if not entity_id:
            continue
        entity = registry.entities.get(entity_id)
        if (
            entity is None
            or entity.platform != "kems"
            or entity.config_entry_id != entry_id
            or entity.unique_id != unique_id
        ):
            continue
        current = states.get(entity_id)
        if current is not None and str(current.state).lower() not in {
            "unavailable",
            "unknown",
        }:
            continue
        registry.async_remove(entity_id)
        removed.append(entity_id)
    return tuple(removed)
