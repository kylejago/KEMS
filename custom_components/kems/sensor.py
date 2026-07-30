"""Sensor platform for KEMS."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KEMSCoordinator
from .entity import KEMSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KEMS sensors."""

    coordinator: KEMSCoordinator = entry.runtime_data

    async_add_entities(
        [
            KEMSStatusSensor(coordinator),
            KEMSCurrentImportRateSensor(coordinator),
            KEMSNextImportRateSensor(coordinator),
            KEMSNextOffPeakStartSensor(coordinator),
            KEMSOffPeakEndSensor(coordinator),
        ]
    )


class KEMSStatusSensor(KEMSEntity, SensorEntity):
    """KEMS status."""

    _attr_name = "Status"
    _attr_unique_id = "kems_status"
    _attr_icon = "mdi:home-lightning-bolt"

    @property
    def native_value(self) -> str:
        """Return the current status."""
        return "Monitoring"


class KEMSCurrentImportRateSensor(KEMSEntity, SensorEntity):
    """Current electricity import rate."""

    _attr_name = "Current Import Rate"
    _attr_unique_id = "kems_current_import_rate"
    _attr_native_unit_of_measurement = "p/kWh"
    _attr_icon = "mdi:cash"
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        """Return current import rate."""
        return self.coordinator.data.current_import_rate


class KEMSNextImportRateSensor(KEMSEntity, SensorEntity):
    """Next electricity import rate."""

    _attr_name = "Next Import Rate"
    _attr_unique_id = "kems_next_import_rate"
    _attr_native_unit_of_measurement = "p/kWh"
    _attr_icon = "mdi:cash-clock"
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        """Return next import rate."""
        return self.coordinator.data.next_import_rate


class KEMSNextOffPeakStartSensor(KEMSEntity, SensorEntity):
    """Next off-peak start."""

    _attr_name = "Next Off-Peak Start"
    _attr_unique_id = "kems_next_offpeak_start"
    _attr_device_class = "timestamp"

    @property
    def native_value(self) -> datetime | None:
        """Return next off-peak start."""
        return self.coordinator.data.next_offpeak_start


class KEMSOffPeakEndSensor(KEMSEntity, SensorEntity):
    """Off-peak end."""

    _attr_name = "Off-Peak End"
    _attr_unique_id = "kems_offpeak_end"
    _attr_device_class = "timestamp"

    @property
    def native_value(self) -> datetime | None:
        """Return off-peak end."""
        return self.coordinator.data.offpeak_end
