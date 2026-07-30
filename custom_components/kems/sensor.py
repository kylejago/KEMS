"""Sensor platform for KEMS."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_EV_POWER, CONF_EV_SOC
from .coordinator import KEMSCoordinator
from .entity import KEMSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KEMS sensors."""
    coordinator = cast(KEMSCoordinator, entry.runtime_data)

    entities: list[SensorEntity] = [
        KEMSStatusSensor(coordinator),
        KEMSCurrentImportRateSensor(coordinator),
        KEMSNextImportRateSensor(coordinator),
        KEMSNextOffPeakStartSensor(coordinator),
        KEMSOffPeakEndSensor(coordinator),
    ]

    if CONF_EV_POWER in entry.data:
        entities.append(KEMSEVPowerSensor(coordinator))
    if CONF_EV_SOC in entry.data:
        entities.append(KEMSEVStateOfChargeSensor(coordinator))

    async_add_entities(entities)


class KEMSStatusSensor(KEMSEntity, SensorEntity):
    """KEMS operating status."""

    _attr_name = "Status"
    _attr_icon = "mdi:home-lightning-bolt"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the status sensor."""
        super().__init__(coordinator, "status")

    @property
    def native_value(self) -> str:
        """Return the current operating status."""
        return "Monitoring"


class KEMSCurrentImportRateSensor(KEMSEntity, SensorEntity):
    """Current electricity import rate."""

    _attr_name = "Current import rate"
    _attr_native_unit_of_measurement = "p/kWh"
    _attr_icon = "mdi:cash"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the current-rate sensor."""
        super().__init__(coordinator, "current_import_rate")

    @property
    def native_value(self) -> float | None:
        """Return the current import rate in pence per kWh."""
        return self.coordinator.data.current_import_rate


class KEMSNextImportRateSensor(KEMSEntity, SensorEntity):
    """Next electricity import rate."""

    _attr_name = "Next import rate"
    _attr_native_unit_of_measurement = "p/kWh"
    _attr_icon = "mdi:cash-clock"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the next-rate sensor."""
        super().__init__(coordinator, "next_import_rate")

    @property
    def native_value(self) -> float | None:
        """Return the next import rate in pence per kWh."""
        return self.coordinator.data.next_import_rate


class KEMSNextOffPeakStartSensor(KEMSEntity, SensorEntity):
    """Next off-peak start timestamp."""

    _attr_name = "Next offpeak start"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the next off-peak start sensor."""
        super().__init__(coordinator, "next_offpeak_start")

    @property
    def native_value(self) -> datetime | None:
        """Return the next off-peak start."""
        return self.coordinator.data.next_offpeak_start


class KEMSOffPeakEndSensor(KEMSEntity, SensorEntity):
    """Off-peak end timestamp."""

    _attr_name = "Offpeak end"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the off-peak end sensor."""
        super().__init__(coordinator, "offpeak_end")

    @property
    def native_value(self) -> datetime | None:
        """Return the off-peak end."""
        return self.coordinator.data.offpeak_end


class KEMSEVPowerSensor(KEMSEntity, SensorEntity):
    """EV charging power."""

    _attr_name = "EV power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the EV power sensor."""
        super().__init__(coordinator, "ev_power")

    @property
    def native_value(self) -> float | None:
        """Return EV charging power."""
        return self.coordinator.data.ev_power_kw


class KEMSEVStateOfChargeSensor(KEMSEntity, SensorEntity):
    """EV state of charge."""

    _attr_name = "EV state of charge"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the EV state-of-charge sensor."""
        super().__init__(coordinator, "ev_soc")

    @property
    def native_value(self) -> float | None:
        """Return EV state of charge."""
        return self.coordinator.data.ev_soc
