"""Sensor platform for KEMS."""

from __future__ import annotations

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
        ]
    )


class KEMSStatusSensor(KEMSEntity, SensorEntity):
    """KEMS status."""

    _attr_name = "Status"
    _attr_unique_id = "kems_status"
    _attr_icon = "mdi:home-lightning-bolt"

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)

    @property
    def native_value(self) -> str:
        """Return integration status."""
        return "Monitoring"


class KEMSCurrentImportRateSensor(KEMSEntity, SensorEntity):
    """Current electricity import rate."""

    _attr_name = "Current Import Rate"
    _attr_unique_id = "kems_current_import_rate"

    _attr_native_unit_of_measurement = "p/kWh"

    _attr_icon = "mdi:cash"

    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: KEMSCoordinator) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)

    @property
    def native_value(self) -> float | None:
        """Return the current import rate."""
        return self.coordinator.data.electricity_rate
