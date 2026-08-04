"""Select entities for the pre-installation KEMS control lab."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_OPERATING_MODE, CONF_VIRTUAL_SCENARIO
from .entity import KEMSEntity
from .kems_core import OPERATING_MODES, VIRTUAL_SCENARIOS
from .runtime_options import async_set_runtime_option


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up control-lab select entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        (
            KEMSOperatingModeSelect(coordinator),
            KEMSVirtualScenarioSelect(coordinator),
        )
    )


class KEMSOperatingModeSelect(KEMSEntity, SelectEntity):
    """Choose the KEMS planning mode without enabling a real backend."""

    _attr_name = "Operating mode"
    _attr_icon = "mdi:tune-variant"
    _attr_options = list(OPERATING_MODES)

    def __init__(self, coordinator) -> None:
        """Initialise the selector."""
        super().__init__(coordinator, "operating_mode_select")

    @property
    def current_option(self) -> str:
        """Return the configured mode."""
        return self.coordinator.settings.control.operating_mode

    async def async_select_option(self, option: str) -> None:
        """Persist a valid mode and reload KEMS."""
        if option not in OPERATING_MODES:
            raise HomeAssistantError(f"Unsupported KEMS mode: {option}")
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_OPERATING_MODE,
            option,
        )


class KEMSVirtualScenarioSelect(KEMSEntity, SelectEntity):
    """Inject a deterministic virtual KH7 test scenario."""

    _attr_name = "Virtual scenario"
    _attr_icon = "mdi:test-tube"
    _attr_options = list(VIRTUAL_SCENARIOS)

    def __init__(self, coordinator) -> None:
        """Initialise the selector."""
        super().__init__(coordinator, "virtual_scenario_select")

    @property
    def current_option(self) -> str:
        """Return the configured scenario."""
        return self.coordinator.settings.control.virtual_scenario

    async def async_select_option(self, option: str) -> None:
        """Persist a valid scenario and reload KEMS."""
        if option not in VIRTUAL_SCENARIOS:
            raise HomeAssistantError(f"Unsupported virtual scenario: {option}")
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_VIRTUAL_SCENARIO,
            option,
        )
