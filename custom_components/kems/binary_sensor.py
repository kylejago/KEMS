"""Binary sensor platform for KEMS."""

from __future__ import annotations

from typing import cast

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_EV_CHARGING, CONF_EV_CONNECTED
from .coordinator import KEMSCoordinator
from .entity import KEMSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KEMS binary sensors."""
    coordinator = cast(KEMSCoordinator, entry.runtime_data)

    entities: list[BinarySensorEntity] = [
        KEMSOffPeakBinarySensor(coordinator),
        KEMSIntelligentSlotBinarySensor(coordinator),
    ]

    if CONF_EV_CONNECTED in entry.data:
        entities.append(KEMSEVConnectedBinarySensor(coordinator))
    if CONF_EV_CHARGING in entry.data:
        entities.append(KEMSEVChargingBinarySensor(coordinator))

    async_add_entities(entities)


class KEMSOffPeakBinarySensor(KEMSEntity, BinarySensorEntity):
    """Whether the configured Octopus tariff is off peak."""

    _attr_name = "Off peak"
    _attr_icon = "mdi:weather-night"

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the off-peak sensor."""
        super().__init__(coordinator, "off_peak")

    @property
    def is_on(self) -> bool | None:
        """Return whether the tariff is currently off peak."""
        return self.coordinator.data.off_peak


class KEMSIntelligentSlotBinarySensor(KEMSEntity, BinarySensorEntity):
    """Whether an Octopus Intelligent slot is active."""

    _attr_name = "Intelligent slot"
    _attr_icon = "mdi:ev-station"

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the Intelligent slot sensor."""
        super().__init__(coordinator, "intelligent_slot")

    @property
    def is_on(self) -> bool | None:
        """Return whether an Intelligent slot is active."""
        return self.coordinator.data.intelligent_slot


class KEMSEVConnectedBinarySensor(KEMSEntity, BinarySensorEntity):
    """Whether an EV is connected."""

    _attr_name = "EV connected"
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the EV-connected sensor."""
        super().__init__(coordinator, "ev_connected")

    @property
    def is_on(self) -> bool | None:
        """Return whether an EV is connected."""
        return self.coordinator.data.ev_connected


class KEMSEVChargingBinarySensor(KEMSEntity, BinarySensorEntity):
    """Whether the EV is charging."""

    _attr_name = "EV charging"
    _attr_icon = "mdi:battery-charging"

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the EV-charging sensor."""
        super().__init__(coordinator, "ev_charging")

    @property
    def is_on(self) -> bool | None:
        """Return whether the EV is charging."""
        return self.coordinator.data.ev_charging
