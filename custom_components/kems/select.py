"""Select entities for simple KEMS operation and the advanced test lab."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_EXPORT_TARIFF_STATUS,
    CONF_OPERATING_MODE,
    CONF_SYSTEM_TYPE,
    CONF_VIRTUAL_SCENARIO,
)
from .entity import KEMSEntity
from .happy_hour import CONF_HAPPY_HOUR_DURATION_HOURS, happy_hour_duration_hours
from .kems_core import (
    CONF_EV_CHARGING_POLICY,
    DEFAULT_EV_POLICY,
    EV_POLICY_KEYS,
    EV_POLICY_LABELS,
    VIRTUAL_SCENARIOS,
    ev_policy_from_options,
)
from .product_types import (
    EXPORT_TARIFF_TYPES,
    EXPORT_TARIFF_TYPE_LABELS,
    EXPORT_TARIFF_TYPE_NONE,
    SYSTEM_TYPE_DEFINITIONS,
    SYSTEM_TYPE_KEMS,
    SYSTEM_TYPE_LIVE_DATA,
    SYSTEM_TYPES,
    USER_MODES,
    export_tariff_type_from_options,
    internal_mode_from_user,
    user_mode_from_internal,
)
from .runtime_options import async_set_runtime_option, async_set_runtime_options
from .update_orchestrator import build_update_select_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up simple user selectors plus advanced engineering controls."""
    coordinator = entry.runtime_data
    entities = [
        KEMSSystemTypeSelect(coordinator),
        KEMSExportTariffSelect(coordinator),
        KEMSOperatingModeSelect(coordinator),
        KEMSEVChargingPolicySelect(coordinator),
        KEMSWeekendHappyHourDurationSelect(coordinator),
        KEMSVirtualScenarioSelect(coordinator),
    ]
    entities.extend(build_update_select_entities(hass, coordinator, entry))
    async_add_entities(entities)


class KEMSSystemTypeSelect(KEMSEntity, SelectEntity):
    """Choose between measured Live Data and the adaptive KEMS product."""

    _attr_name = "System type"
    _attr_icon = "mdi:home-cog-outline"
    _attr_options = [SYSTEM_TYPE_DEFINITIONS[key].label for key in SYSTEM_TYPES]

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "system_type_select")

    @property
    def current_option(self) -> str:
        definition = SYSTEM_TYPE_DEFINITIONS.get(self.coordinator.settings.system_type)
        return definition.label if definition else SYSTEM_TYPE_DEFINITIONS[SYSTEM_TYPE_KEMS].label

    async def async_select_option(self, option: str) -> None:
        selected = next(
            (
                key
                for key in SYSTEM_TYPES
                if SYSTEM_TYPE_DEFINITIONS[key].label == option
            ),
            None,
        )
        if selected is None:
            raise HomeAssistantError(f"Unsupported KEMS system type: {option}")
        changes = {CONF_SYSTEM_TYPE: selected}
        if selected == SYSTEM_TYPE_LIVE_DATA:
            changes[CONF_OPERATING_MODE] = "observe"
        await async_set_runtime_options(self.hass, self.coordinator.entry, changes)


class KEMSExportTariffSelect(KEMSEntity, SelectEntity):
    """Select the export tariff that chooses KEMS's internal optimisation path."""

    _attr_name = "Export tariff"
    _attr_icon = "mdi:cash-sync"
    _attr_options = [EXPORT_TARIFF_TYPE_LABELS[key] for key in EXPORT_TARIFF_TYPES]

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "export_tariff_type")

    @property
    def current_option(self) -> str:
        selected = export_tariff_type_from_options(self.coordinator.entry.options)
        return EXPORT_TARIFF_TYPE_LABELS[selected]

    async def async_select_option(self, option: str) -> None:
        selected = next(
            (key for key, label in EXPORT_TARIFF_TYPE_LABELS.items() if label == option),
            None,
        )
        if selected is None:
            raise HomeAssistantError(f"Unsupported KEMS export tariff: {option}")
        await async_set_runtime_options(
            self.hass,
            self.coordinator.entry,
            {
                "export_tariff_type": selected,
                # The existing simulation engine already has the correct
                # no-export safety path behind this established option.
                CONF_EXPORT_TARIFF_STATUS: (
                    "awaiting" if selected == EXPORT_TARIFF_TYPE_NONE else "active"
                ),
            },
        )


class KEMSOperatingModeSelect(KEMSEntity, SelectEntity):
    """Choose Live, Simulate or Control without exposing engineering modes."""

    _attr_name = "Mode"
    _attr_icon = "mdi:tune-variant"
    _attr_options = list(USER_MODES)

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "operating_mode_select")

    @property
    def current_option(self) -> str:
        return user_mode_from_internal(self.coordinator.settings.control.operating_mode)

    async def async_select_option(self, option: str) -> None:
        if option not in USER_MODES:
            raise HomeAssistantError(f"Unsupported KEMS mode: {option}")
        if (
            self.coordinator.settings.system_type == SYSTEM_TYPE_LIVE_DATA
            and option != "Live"
        ):
            raise HomeAssistantError("Live Data supports Live mode only")
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_OPERATING_MODE,
            internal_mode_from_user(option),
        )


class KEMSEVChargingPolicySelect(KEMSEntity, SelectEntity):
    """Choose the shadow EV charging policy; cheap-window is the safe default."""

    _attr_name = "EV charging policy"
    _attr_icon = "mdi:ev-station"
    _attr_options = [EV_POLICY_LABELS[key] for key in EV_POLICY_KEYS]

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "ev_charging_policy")

    @property
    def current_option(self) -> str:
        policy = ev_policy_from_options(self.coordinator.entry.options)
        return EV_POLICY_LABELS.get(policy, EV_POLICY_LABELS[DEFAULT_EV_POLICY])

    async def async_select_option(self, option: str) -> None:
        selected = next(
            (key for key, label in EV_POLICY_LABELS.items() if label == option), None
        )
        if selected is None:
            raise HomeAssistantError(f"Unsupported EV charging policy: {option}")
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_EV_CHARGING_POLICY,
            selected,
        )


class KEMSWeekendHappyHourDurationSelect(KEMSEntity, SelectEntity):
    """Choose whether one or two booked Weekend Happy Hours are consecutive."""

    _attr_name = "Weekend Happy Hour duration"
    _attr_icon = "mdi:timer-plus-outline"
    _attr_options = ["1 hour", "2 hours"]

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "weekend_happy_hour_duration")

    @property
    def current_option(self) -> str:
        duration = happy_hour_duration_hours(self.coordinator.entry.options)
        return f"{duration} hour" if duration == 1 else f"{duration} hours"

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            raise HomeAssistantError(f"Unsupported Happy Hour duration: {option}")
        duration = 2 if option.startswith("2") else 1
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_HAPPY_HOUR_DURATION_HOURS,
            duration,
        )


class KEMSVirtualScenarioSelect(KEMSEntity, SelectEntity):
    """Inject a deterministic virtual test scenario from the advanced lab."""

    _attr_name = "Advanced test scenario"
    _attr_icon = "mdi:test-tube"
    _attr_options = list(VIRTUAL_SCENARIOS)
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "virtual_scenario_select")

    @property
    def current_option(self) -> str:
        return self.coordinator.settings.control.virtual_scenario

    async def async_select_option(self, option: str) -> None:
        if option not in VIRTUAL_SCENARIOS:
            raise HomeAssistantError(f"Unsupported virtual scenario: {option}")
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_VIRTUAL_SCENARIO,
            option,
        )
