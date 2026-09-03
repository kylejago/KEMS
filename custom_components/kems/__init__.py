"""KEMS integration setup."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .agile_simulation_presentation import install_agile_simulation_presentation
from .agile_slots_state import async_setup_agile_slots_state
from .collector import Collector
from .const import (
    CONF_BATTERY_RESERVE,
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
    DEFAULT_OPTIONS,
)
from .coordinator import KEMSCoordinator
from .dashboard import async_sync_managed_dashboard
from .dashboard_pipeline import install_dashboard_pipeline
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
from .source_authority import async_reconcile_source_mappings
from .update_orchestrator import async_unload_update_orchestrator
from .update_orchestrator_convergent import async_setup_update_orchestrator

LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TIME,
    Platform.DATETIME,
]


def _alpha876_planning_options(options: dict[str, object]) -> dict[str, object]:
    """Migrate legacy sub-15% reserve values to the new planning target floor."""
    planning_minimum = float(DEFAULT_OPTIONS[CONF_BATTERY_RESERVE])
    try:
        configured = float(options.get(CONF_BATTERY_RESERVE, planning_minimum))
    except (TypeError, ValueError):
        configured = planning_minimum
    options[CONF_BATTERY_RESERVE] = max(configured, planning_minimum)
    return options


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up KEMS from a config entry."""
    # Alpha8.19 keeps the existing billing state but replaces the historical
    # dashboard compositor with one fresh packaged customer dashboard.
    install_energy_bill_dashboard_patch()
    install_dashboard_pipeline()
    try:
        await async_sync_managed_dashboard(hass)
    except (OSError, ValueError):
        LOGGER.exception(
            "Unable to update the managed KEMS dashboard; continuing KEMS setup"
        )

    options = _alpha876_planning_options(dict(entry.options))
    if options != dict(entry.options):
        hass.config_entries.async_update_entry(entry, options=options)
        LOGGER.info(
            "KEMS migrated the legacy battery reserve to a minimum 15%% "
            "optimiser target; the independent hard safety floor remains 10%%"
        )

    validation = await async_validate_entity_mappings(hass, dict(entry.data))
    discovery = await async_discover_entities(hass)
    authority = await async_reconcile_source_mappings(
        hass,
        validation.accepted,
        discovery.mappings,
    )
    final_validation = await async_validate_entity_mappings(hass, authority.mappings)
    enriched = final_validation.accepted

    if enriched != dict(entry.data):
        hass.config_entries.async_update_entry(entry, data=enriched)
    if validation.rejected:
        LOGGER.warning("KEMS rejected unsafe source mappings: %s", validation.summary())
    if authority.upgrades:
        LOGGER.info(
            "KEMS promoted source mappings to higher-priority platforms: %s",
            authority.upgrades,
        )
    if final_validation.rejected:
        LOGGER.warning(
            "KEMS rejected reconciled source mappings: %s",
            final_validation.summary(),
        )

    unresolved_rejected = {
        key: details
        for key, details in validation.rejected.items()
        if key not in enriched
    }
    unresolved_rejected.update(final_validation.rejected)
    source_validation = SourceValidationResult(
        accepted=enriched,
        rejected=unresolved_rejected,
    )
    entities = KEMSEntities.from_entry_data(enriched)
    settings = KEMSSettings.from_options(options)
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
    configure_ev_charge_policy(coordinator._control, options)

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    async_setup_energy_bill_state(hass, entry, coordinator)
    async_setup_agile_slots_state(hass, entry, coordinator)
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
    options = _alpha876_planning_options(dict(entry.options))
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
