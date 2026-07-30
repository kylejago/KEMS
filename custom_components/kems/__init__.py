"""KEMS integration setup."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .collector import Collector
from .coordinator import KEMSCoordinator
from .providers.entity_map import KEMSEntities
from .providers.octopus import OctopusProvider
from .providers.ohme import OhmeProvider

LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up KEMS from a config entry."""
    entities = KEMSEntities.from_entry_data(dict(entry.data))

    collector = Collector(
        octopus=OctopusProvider(hass, entities),
        ohme=OhmeProvider(hass, entities),
    )
    coordinator = KEMSCoordinator(hass, entry, collector)

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    LOGGER.info("KEMS initialised in observe-only mode")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a KEMS config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
