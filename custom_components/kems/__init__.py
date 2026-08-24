"""KEMS integration setup."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .agile_simulation_presentation import install_agile_simulation_presentation
from .collector import Collector
from .const import (
    CONF_EV_POWER,
    CONF_EXPORT_LIMIT,
    CONF_EXPORT_RATE,
    CONF_EXPORT_TARIFF_STATUS,
    CONF_INTELLIGENT_SLOTS_ENABLED,
    CONF_INVERTER_LIMIT,
    CONF_MANUAL_DAY_RATE,
    CONF_MANUAL_OFFPEAK_END,
    CONF_MANUAL_OFFPEAK_RATE,
    CONF_MANUAL_OFFPEAK_START,
    CONF_MANUAL_STANDING_CHARGE,
    CONF_MAX_CHARGE,
    CONF_MAX_DISCHARGE,
    CONF_SIMULATION_STRATEGY,
    CONF_SITE_IMPORT_LIMIT,
    CONF_TARIFF_MODE,
)
from .coordinator import KEMSCoordinator
from .dashboard import async_sync_managed_dashboard
from .energy_bill_presentation import (
    async_setup_energy_bill_state,
    install_energy_bill_dashboard_patch,
)
from .entity_discovery import (
    SourceValidationResult,
    async_discover_entities,
    async_validate_entity_mappings,
)
from .kems_core import configure_ev_charge_policy
from .providers.entity_map import KEMSEntities
from .providers.foxess import FoxESSProvider
from .providers.gas import GasProvider
from .providers.octoplus import OctoplusProvider
from .providers.octopus import OctopusProvider
from .providers.ohme import OhmeProvider
from .settings import KEMSSettings
from .update_orchestrator import async_unload_update_orchestrator
from .update_orchestrator_reliable import async_setup_update_orchestrator

LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TIME,
    Platform.DATETIME,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up KEMS from a config entry."""
    # Install the reporting-only Alpha8.13 bill presentation before the managed
    # dashboard is rendered. It does not alter planning or hardware permissions.
    install_energy_bill_dashboard_patch()
    try:
        await async_sync_managed_dashboard(hass)
    except (OSError, ValueError):
        LOGGER.exception(
            "Unable to update the managed KEMS dashboard; continuing KEMS setup"
        )

    validation = await async_validate_entity_mappings(hass, dict(entry.data))
    discovery = await async_discover_entities(hass)
    enriched = {**validation.accepted, **discovery.mappings}

    if enriched != dict(entry.data):
        hass.config_entries.async_update_entry(entry, data=enriched)
    if validation.rejected:
        LOGGER.warning("KEMS rejected unsafe source mappings: %s", validation.summary())

    source_validation = SourceValidationResult(
        accepted=enriched, rejected=validation.rejected
    )
    entities = KEMSEntities.from_entry_data(enriched)
    settings = KEMSSettings.from_options(entry.options)
    collector = Collector(
        octopus=OctopusProvider(
            hass, entities, stale_data_seconds=settings.control.stale_data_seconds
        ),
        gas=GasProvider(hass, entities, settings.gas_kwh_per_m3),
        ohme=OhmeProvider(hass, entities),
        foxess=FoxESSProvider(
            hass, entities, stale_data_seconds=settings.control.stale_data_seconds
        ),
        octoplus=OctoplusProvider(hass, entities),
        settings=settings,
    )
    coordinator = KEMSCoordinator(
        hass,
        entry,
        collector,
        entities,
        settings,
        source_validation=source_validation,
    )
    configure_ev_charge_policy(coordinator._control, entry.options)

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    async_setup_energy_bill_state(hass, entry, coordinator)
    update_orchestrator = await async_setup_update_orchestrator(hass, entry)
    if (
        update_orchestrator.policy.automatic_updates
        and not update_orchestrator.policy.automatic_restart
    ):
        LOGGER.warning(
            "KEMS repaired a legacy update policy with automatic updates enabled "
            "but automatic maintenance restart disabled"
        )
        await update_orchestrator.async_set_policy(automatic_restart=True)
    install_agile_simulation_presentation()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    LOGGER.info(
        "KEMS initialised with read-only control lab; real hardware writes are blocked"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload KEMS config entry."""
    coordinator: KEMSCoordinator = entry.runtime_data
    await async_unload_update_orchestrator(hass, entry)
    await coordinator.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate earlier KEMS config entries to the current schema."""
    if entry.version > 13:
        return False

    data = dict(entry.data)
    options = dict(entry.options)
    old_ev_power = data.pop("ev_power", None)
    if old_ev_power and not data.get(CONF_EV_POWER):
        data[CONF_EV_POWER] = old_ev_power

    if entry.version < 8:
        options[CONF_INVERTER_LIMIT] = 7.0
        options[CONF_MAX_CHARGE] = 7.0
        options[CONF_MAX_DISCHARGE] = 7.0
        try:
            previous_export_limit = float(options.get(CONF_EXPORT_LIMIT, 7.0))
        except (TypeError, ValueError):
            previous_export_limit = 7.0
        options[CONF_EXPORT_LIMIT] = min(max(previous_export_limit, 0.0), 7.0)
        options[CONF_EXPORT_RATE] = 12.0
        options[CONF_SIMULATION_STRATEGY] = "paced_export"

    if entry.version < 11:
        options.setdefault(CONF_SITE_IMPORT_LIMIT, 0.0)

    if entry.version < 12:
        options.setdefault(CONF_TARIFF_MODE, "automatic")
        options.setdefault(CONF_MANUAL_DAY_RATE, 28.3036)
        options.setdefault(CONF_MANUAL_OFFPEAK_RATE, 3.4933)
        options.setdefault(CONF_MANUAL_STANDING_CHARGE, 53.70435)
        options.setdefault(CONF_MANUAL_OFFPEAK_START, "23:30:00")
        options.setdefault(CONF_MANUAL_OFFPEAK_END, "05:30:00")
        options.setdefault(CONF_INTELLIGENT_SLOTS_ENABLED, True)

    if entry.version < 13:
        options.setdefault(CONF_EXPORT_TARIFF_STATUS, "active")

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        version=13,
        minor_version=0,
    )
    return True
