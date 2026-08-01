"""KEMS integration setup."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .collector import Collector
from .const import CONF_EV_POWER
from .coordinator import KEMSCoordinator
from .entity_discovery import async_discover_entities
from .providers.entity_map import KEMSEntities
from .providers.foxess import FoxESSProvider
from .providers.gas import GasProvider
from .providers.octopus import OctopusProvider
from .providers.ohme import OhmeProvider
from .settings import KEMSSettings

LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up KEMS from a config entry."""
    discovery = await async_discover_entities(hass)
    enriched = dict(entry.data)
    changed = False
    for key, entity_id in discovery.mappings.items():
        if not enriched.get(key):
            enriched[key] = entity_id
            changed = True
    if changed:
        hass.config_entries.async_update_entry(entry, data=enriched)

    entities = KEMSEntities.from_entry_data(enriched)
    settings = KEMSSettings.from_options(entry.options)
    collector = Collector(
        octopus=OctopusProvider(hass, entities),
        gas=GasProvider(hass, entities, settings.gas_kwh_per_m3),
        ohme=OhmeProvider(hass, entities),
        foxess=FoxESSProvider(hass, entities),
    )
    coordinator = KEMSCoordinator(hass, entry, collector, entities, settings)

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    LOGGER.info("KEMS initialised in read-only proposal simulation and whole-home mode")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a KEMS config entry."""
    coordinator: KEMSCoordinator = entry.runtime_data
    await coordinator.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate earlier KEMS config entries to the current schema."""
    if entry.version > 5:
        return False

    data = dict(entry.data)
    old_ev_power = data.pop("ev_power", None)
    if old_ev_power and not data.get(CONF_EV_POWER):
        data[CONF_EV_POWER] = old_ev_power

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        version=5,
        minor_version=0,
    )
    return True
