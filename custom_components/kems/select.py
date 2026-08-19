"""Select entities for simple KEMS operation and the advanced test lab."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_OPERATING_MODE, CONF_SYSTEM_TYPE, CONF_VIRTUAL_SCENARIO
from .entity import KEMSEntity
from .kems_core import VIRTUAL_SCENARIOS
from .product_types import (
    SYSTEM_TYPE_DEFINITIONS,
    SYSTEM_TYPE_LIVE_DATA,
    SYSTEM_TYPES,
    USER_MODES,
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
        KEMSOperatingModeSelect(coordinator),
        KEMSVirtualScenarioSelect(coordinator),
    ]
    entities.extend(build_update_select_entities(hass, coordinator, entry))
    async_add_entities(entities)


class KEMSSystemTypeSelect(KEMSEntity, SelectEntity):
    """Choose the user-facing KEMS capability level."""

    _attr_name = "System type"
    _attr_icon = "mdi:home-cog-outline"
    _attr_options = [SYSTEM_TYPE_DEFINITIONS[key].label for key in SYSTEM_TYPES]

    def __init__(self, coordinator) -> None:
        """Initialise the selector."""
        super().__init__(coordinator, "system_type_select")

    @property
    def current_option(self) -> str:
        """Return the friendly configured system type."""
        definition = SYSTEM_TYPE_DEFINITIONS.get(self.coordinator.settings.system_type)
        return definition.label if definition else SYSTEM_TYPE_DEFINITIONS[SYSTEM_TYPES[-1]].label

    async def async_select_option(self, option: str) -> None:
        """Persist a valid type; Live Data also atomically disables control."""
        selected = next(
            (key for key, definition in SYSTEM_TYPE_DEFINITIONS.items() if definition.label == option),
            None,
        )
        if selected is None:
            raise HomeAssistantError(f"Unsupported KEMS system type: {option}")
        changes = {CONF_SYSTEM_TYPE: selected}
        if selected == SYSTEM_TYPE_LIVE_DATA:
            changes[CONF_OPERATING_MODE] = "observe"
        await async_set_runtime_options(self.hass, self.coordinator.entry, changes)


class KEMSOperatingModeSelect(KEMSEntity, SelectEntity):
    """Choose Live, Simulate or Control without exposing engineering modes."""

    _attr_name = "Mode"
    _attr_icon = "mdi:tune-variant"
    _attr_options = list(USER_MODES)

    def __init__(self, coordinator) -> None:
        """Initialise the selector."""
        super().__init__(coordinator, "operating_mode_select")

    @property
    def current_option(self) -> str:
        """Return the simple user-facing mode."""
        return user_mode_from_internal(self.coordinator.settings.control.operating_mode)

    async def async_select_option(self, option: str) -> None:
        """Persist a simple mode while respecting Live Data capabilities."""
        if option not in USER_MODES:
            raise HomeAssistantError(f"Unsupported KEMS mode: {option}")
        if self.coordinator.settings.system_type == SYSTEM_TYPE_LIVE_DATA and option != "Live":
            raise HomeAssistantError("Live Data supports Live mode only")
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_OPERATING_MODE,
            internal_mode_from_user(option),
        )


class KEMSVirtualScenarioSelect(KEMSEntity, SelectEntity):
    """Inject a deterministic virtual test scenario from the advanced lab."""

    _attr_name = "Advanced test scenario"
    _attr_icon = "mdi:test-tube"
    _attr_options = list(VIRTUAL_SCENARIOS)
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator) -> None:
        """Initialise the selector."""
        super().__init__(coordinator, "virtual_scenario_select")

    @property
    def current_option(self) -> str:
        """Return the configured scenario."""
        return self.coordinator.settings.control.virtual_scenario

    async def async_select_option(self, option: str) -> None:
        """Persist a valid advanced scenario and reload KEMS."""
        if option not in VIRTUAL_SCENARIOS:
            raise HomeAssistantError(f"Unsupported virtual scenario: {option}")
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_VIRTUAL_SCENARIO,
            option,
        )
