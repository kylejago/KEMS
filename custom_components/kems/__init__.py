"""KEMS."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .collector import Collector
from .coordinator import KEMSCoordinator
from .providers.octopus import OctopusProvider
from .providers.ohme import OhmeProvider

LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
]


async def async_setup(
    hass: HomeAssistant,
    config: dict,
) -> bool:
    """Set up KEMS."""

    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up a KEMS config entry."""

    octopus = OctopusProvider(hass)
    ohme = OhmeProvider(hass)

    collector = Collector(
        octopus=octopus,
        ohme=ohme,
    )

    coordinator = KEMSCoordinator(
        hass=hass,
        collector=collector,
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    LOGGER.info("KEMS initialised")

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload KEMS."""

    return await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )
