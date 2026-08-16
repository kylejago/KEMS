"""Time controls for the KEMS update maintenance window."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .update_orchestrator import build_update_time_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up maintenance-window time entities."""
    coordinator = entry.runtime_data
    async_add_entities(build_update_time_entities(hass, coordinator, entry))
