"""Safety switches for the KEMS control-development lab and event planning."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .battery_installation import (
    battery_installed_from_options,
    battery_telemetry_snapshot,
    install_battery_installation_contract,
)
from .commissioning import build_commissioning_snapshot
from .const import (
    CONF_BATTERY_INSTALLED,
    CONF_CONTROL_ENABLED,
    CONF_EMERGENCY_STOP,
    CONF_HAPPY_HOUR_OHME_CONTROL_ENABLED,
    CONF_SYSTEM_COMMISSIONED,
)
from .entity import KEMSEntity
from .happy_hour import CONF_HAPPY_HOUR_ENABLED
from .happy_hour_auto_join import (
    CONF_HAPPY_HOUR_AUTO_JOIN_ENABLED,
    happy_hour_auto_join_state,
)
from .runtime_options import async_set_runtime_option
from .update_orchestrator import build_update_switch_entities

# Apply the Alpha9.34 commissioning contract before any switch state is exposed.
# The patch is idempotent and does not grant control/write authority.
install_battery_installation_contract()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up control-lab and event-planning switches."""
    coordinator = entry.runtime_data
    entities = [
        KEMSBatteryInstalledSwitch(coordinator),
        KEMSEmergencyStopSwitch(coordinator),
        KEMSCommissionedForControlSwitch(coordinator),
        KEMSMasterControlEnableSwitch(coordinator),
        KEMSWeekendHappyHourPlanningSwitch(coordinator),
        KEMSWeekendHappyHourAutoJoinSwitch(coordinator),
        KEMSHappyHourOhmeControlSwitch(coordinator),
    ]
    entities.extend(build_update_switch_entities(hass, coordinator, entry))
    async_add_entities(entities)


class KEMSBatteryInstalledSwitch(KEMSEntity, SwitchEntity):
    """Declare whether the physical battery has actually been installed."""

    _attr_name = "Battery installed"
    _attr_icon = "mdi:battery-check-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "battery_installed")

    @property
    def is_on(self) -> bool:
        """Return the authoritative physical installation setting."""
        return battery_installed_from_options(self.coordinator.entry.options)

    @property
    def extra_state_attributes(self):
        """Expose installation-vs-telemetry evidence beside the setting."""
        assessment = battery_telemetry_snapshot(
            self.hass,
            self.coordinator.entities.as_dict(),
            installed=self.is_on,
        )
        return {
            "installation_status": "Installed" if self.is_on else "Not installed",
            "telemetry_status": assessment.state,
            "telemetry_detail": assessment.detail,
            "no_battery_sentinel_detected": assessment.no_battery_sentinel_detected,
            "setting_telemetry_mismatch": assessment.setting_telemetry_mismatch,
            "setting_is_authoritative": True,
            "control_authority": (
                "None — declaring the battery installed never commissions the system "
                "or permits inverter writes"
            ),
        }

    async def async_turn_on(self, **kwargs) -> None:
        """Declare that the battery is physically fitted, then reload KEMS."""
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_BATTERY_INSTALLED,
            True,
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Declare that the battery is not physically fitted, then reload KEMS."""
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_BATTERY_INSTALLED,
            False,
        )


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


class KEMSCommissionedForControlSwitch(KEMSEntity, SwitchEntity):
    """Explicit user acknowledgement after technical commissioning passes."""

    _attr_name = "Commissioned for control"
    _attr_icon = "mdi:check-decagram-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "commissioned_for_control_switch")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.settings.control.commissioned)

    @property
    def extra_state_attributes(self):
        readiness = build_commissioning_snapshot(self.hass, self.coordinator)
        return {
            "technical_ready_for_control": bool(readiness.get("ready_for_control")),
            "commissioning_state": readiness.get("state"),
            "maximum_allowed_stage": readiness.get("maximum_allowed_stage"),
            "setting_is_authoritative": True,
            "control_authority": (
                "Acknowledgement only; Control mode and Master control enable "
                "must also be active before bounded FoxESS writes are permitted"
            ),
        }

    async def async_turn_on(self, **kwargs) -> None:
        readiness = build_commissioning_snapshot(self.hass, self.coordinator)
        if not readiness.get("ready_for_control"):
            raise HomeAssistantError(
                "KEMS control-critical commissioning evidence is not ready"
            )
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_SYSTEM_COMMISSIONED,
            True,
        )

    async def async_turn_off(self, **kwargs) -> None:
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_SYSTEM_COMMISSIONED,
            False,
        )


class KEMSMasterControlEnableSwitch(KEMSEntity, SwitchEntity):
    """Master opt-in for the bounded, commissioned FoxESS backend."""

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
        """Record the explicit master control opt-in."""
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


class KEMSWeekendHappyHourAutoJoinSwitch(KEMSEntity, SwitchEntity):
    """Explicit opt-in for KEMS to book the recommended Octopus Happy Hour."""

    _attr_name = "Weekend Happy Hour auto join"
    _attr_icon = "mdi:calendar-check-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "weekend_happy_hour_auto_join")

    @property
    def is_on(self) -> bool:
        """Return the explicit external-account booking permission."""
        return bool(
            self.coordinator.entry.options.get(
                CONF_HAPPY_HOUR_AUTO_JOIN_ENABLED,
                False,
            )
        )

    @property
    def extra_state_attributes(self):
        """Expose the recommendation, economics and all booking safety gates."""
        state = happy_hour_auto_join_state(self.coordinator)
        return {
            **state,
            "setting_is_authoritative": True,
            "default": "off",
            "simulation_can_book": False,
            "control_authority": (
                "Octopus account booking only; battery/EV dispatch remains owned by "
                "the existing KEMS control safety layers"
            ),
        }

    async def async_turn_on(self, **kwargs) -> None:
        """Allow booking only when the independent runtime gates also pass."""
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_HAPPY_HOUR_AUTO_JOIN_ENABLED,
            True,
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Revoke external Happy Hour booking permission immediately."""
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_HAPPY_HOUR_AUTO_JOIN_ENABLED,
            False,
        )


class KEMSHappyHourOhmeControlSwitch(KEMSEntity, SwitchEntity):
    """Explicitly allow KEMS to own Ohme mode during automatic Happy Hour."""

    _attr_name = "Happy Hour Ohme control"
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "happy_hour_ohme_control")

    @property
    def is_on(self) -> bool:
        return bool(
            self.coordinator.entry.options.get(
                CONF_HAPPY_HOUR_OHME_CONTROL_ENABLED,
                False,
            )
        )

    async def async_turn_on(self, **kwargs) -> None:
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_HAPPY_HOUR_OHME_CONTROL_ENABLED,
            True,
        )

    async def async_turn_off(self, **kwargs) -> None:
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_HAPPY_HOUR_OHME_CONTROL_ENABLED,
            False,
        )
