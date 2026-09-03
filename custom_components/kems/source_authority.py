"""Deterministic source ownership for KEMS discovery and commissioning.

A validated configured source remains authoritative across restarts. Automatic
entity discovery may fill a missing role or promote a role to an explicitly
higher-priority integration platform, but it must not silently replace one valid
source with another source from the same platform.

This preserves the useful pre-install Octopus current-demand fallback while
allowing house/grid roles to promote automatically to FoxESS Modbus once the
commissioned physical telemetry appears. It also exposes one shared definition
of the physical source roles that must never alias each other at commissioning.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_BATTERY_CURRENT,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_VOLTAGE,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_HOUSE_LOAD,
    CONF_SOLAR_POWER,
)
from .entity_discovery import RULES

PHYSICAL_SOURCE_KEYS = (
    CONF_HOUSE_LOAD,
    CONF_BATTERY_SOC,
    CONF_BATTERY_POWER,
    CONF_BATTERY_VOLTAGE,
    CONF_BATTERY_CURRENT,
    CONF_SOLAR_POWER,
    CONF_GRID_IMPORT,
    CONF_GRID_EXPORT,
)


@dataclass(frozen=True, slots=True)
class SourceAuthorityResult:
    """Final deterministic mappings plus any intentional platform promotions."""

    mappings: dict[str, str]
    upgrades: dict[str, dict[str, str]]


def _platform_rank(key: str, platform: str | None) -> int:
    """Return the declared platform priority for one source role."""
    rule = next((item for item in RULES if item.key == key), None)
    if rule is None:
        return 10_000
    normalised = (platform or "").casefold().strip()
    try:
        return rule.platforms.index(normalised)
    except ValueError:
        return len(rule.platforms) + 1


def reconcile_source_mappings(
    accepted: Mapping[str, str],
    discovered: Mapping[str, str],
    platform_by_entity: Mapping[str, str],
) -> SourceAuthorityResult:
    """Reconcile discovery without replacing an equal-authority valid source.

    Platform ordering in ``entity_discovery.RULES`` is the source-authority
    ordering. Discovery can therefore promote Octopus fallback data to FoxESS,
    or Octopus Energy Intelligent data to the dedicated Intelligent integration,
    but a different entity from the same platform cannot silently take over.
    """
    mappings = dict(accepted)
    upgrades: dict[str, dict[str, str]] = {}

    for key, discovered_entity in discovered.items():
        existing_entity = mappings.get(key)
        if not existing_entity:
            mappings[key] = discovered_entity
            continue
        if existing_entity == discovered_entity:
            continue

        existing_platform = platform_by_entity.get(existing_entity)
        discovered_platform = platform_by_entity.get(discovered_entity)
        if _platform_rank(key, discovered_platform) >= _platform_rank(
            key, existing_platform
        ):
            continue

        mappings[key] = discovered_entity
        upgrades[key] = {
            "from": existing_entity,
            "to": discovered_entity,
            "from_platform": existing_platform or "unknown",
            "to_platform": discovered_platform or "unknown",
        }

    return SourceAuthorityResult(mappings=mappings, upgrades=upgrades)


async def async_reconcile_source_mappings(
    hass: HomeAssistant,
    accepted: Mapping[str, str],
    discovered: Mapping[str, str],
) -> SourceAuthorityResult:
    """Reconcile source mappings using live entity-registry platform ownership."""
    registry = er.async_get(hass)
    entity_ids = set(accepted.values()) | set(discovered.values())
    platform_by_entity: dict[str, str] = {}
    for entity_id in entity_ids:
        entry = registry.async_get(entity_id)
        if entry is not None:
            platform_by_entity[entity_id] = str(entry.platform).casefold().strip()
    return reconcile_source_mappings(accepted, discovered, platform_by_entity)


def duplicate_physical_sources(
    mappings: Mapping[str, str],
) -> dict[str, tuple[str, ...]]:
    """Return physical telemetry entities assigned to more than one source role."""
    roles_by_entity: dict[str, list[str]] = defaultdict(list)
    for key in PHYSICAL_SOURCE_KEYS:
        entity_id = mappings.get(key)
        if entity_id:
            roles_by_entity[str(entity_id)].append(key)
    return {
        entity_id: tuple(sorted(keys))
        for entity_id, keys in sorted(roles_by_entity.items())
        if len(keys) > 1
    }
