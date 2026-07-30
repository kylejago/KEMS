"""Sensor platform for KEMS."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KEMS sensors."""

    async_add_entities([KEMSStatusSensor()])


class KEMSStatusSensor(SensorEntity):
    """KEMS status."""

    _attr_has_entity_name = True

    _attr_name = "Status"

    _attr_unique_id = "kems_status"

    _attr_native_value = "Monitoring"

    _attr_icon = "mdi:home-lightning-bolt"
