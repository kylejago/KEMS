"""Safety switches for the KEMS control-development lab and event planning."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CONTROL_ENABLED, CONF_EMERGENCY_STOP
from .entity import KEMSEntity
from .happy_hour import CONF_HAPPY_HOUR_ENABLED
from .runtime_options import async_set_runtime_option
from .update_orchestrator import build_update_switch_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up control-lab and event-planning switches."""
    coordinator = entry.runtime_data
    entities = [
        KEMSEmergencyStopSwitch(coordinator),
        KEMSMasterControlEnableSwitch(coordinator),
        KEMSWeekendHappyHourPlanningSwitch(coordinator),
    ]
    entities.extend(build_update_switch_entities(hass, coordinator, entry))
    async_add_entities(entities)


class KEMSEmergencyStopSwitch(KEMSEntity, SwitchEntity):
    """Latch a software stop for every KEMS desired command."""

    _attr_name = "Emergency stop"
    _attr_icon = "mdi:alert-octagon"

    def __init__(self, coordinator) -> None:
        """Initialise the emergency-stop switch."""
        super().__init__(coordinator, "emergency_stop_switch")

    @property
    def is_on(self) -> bool:
        """Return whether the stop is latched."""
        return self.coordinator.settings.control.emergency_stop

    async def async_turn_on(self, **kwargs) -> None:
        """Latch the emergency stop."""
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_EMERGENCY_STOP,
            True,
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Clear the software stop after the user has checked the system."""
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_EMERGENCY_STOP,
            False,
        )


class KEMSMasterControlEnableSwitch(KEMSEntity, SwitchEntity):
    """Master opt-in; alpha2 still hard-blocks all real writes."""

    _attr_name = "Master control enable"
    _attr_icon = "mdi:shield-key-outline"

    def __init__(self, coordinator) -> None:
        """Initialise the master switch."""
        super().__init__(coordinator, "master_control_enable_switch")

    @property
    def is_on(self) -> bool:
        """Return the requested master-enable state."""
        return self.coordinator.settings.control.control_enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Record opt-in; no real backend exists in alpha2."""
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_CONTROL_ENABLED,
            True,
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Disable the master opt-in."""
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_CONTROL_ENABLED,
            False,
        )


class KEMSWeekendHappyHourPlanningSwitch(KEMSEntity, SwitchEntity):
    """Enable or cancel the manually entered Weekend Happy Hour plan."""

    _attr_name = "Weekend Happy Hour planning"
    _attr_icon = "mdi:weather-sunny-clock"

    def __init__(self, coordinator) -> None:
        """Initialise the Happy Hour planning switch."""
        super().__init__(coordinator, "weekend_happy_hour_planning")

    @property
    def is_on(self) -> bool:
        """Return whether the manual event is enabled."""
        return bool(self.coordinator.entry.options.get(CONF_HAPPY_HOUR_ENABLED, False))

    async def async_turn_on(self, **kwargs) -> None:
        """Enable the manually selected Happy Hour."""
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_HAPPY_HOUR_ENABLED,
            True,
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Disable/cancel Happy Hour planning without deleting the chosen time."""
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_HAPPY_HOUR_ENABLED,
            False,
        )
