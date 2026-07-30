"""KEMS."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .collector import Collector
from .coordinator import KEMSCoordinator
from .providers.octopus import OctopusProvider
from .providers.ohme import OhmeProvider

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
    """Set up KEMS."""

    # Create providers
    octopus = OctopusProvider(hass)
    ohme = OhmeProvider(hass)

    # Create collector
    collector = Collector(
        octopus=octopus,
        ohme=ohme,
    )

    # Create coordinator
    coordinator = KEMSCoordinator(
        hass=hass,
        collector=collector,
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator for entities
    entry.runtime_data = coordinator

    # Load platforms
    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

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
