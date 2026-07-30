"""Binary sensor platform for KEMS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_BATTERY_SOC,
    CONF_EV_CHARGING,
    CONF_EV_CONNECTED,
    CONF_EV_STATUS,
    CONF_INTELLIGENT_SLOT,
    CONF_OFF_PEAK,
)
from .entity import KEMSEntity
from .kems_core import KEMSData

IsOnFn = Callable[[KEMSData], bool | None]


@dataclass(frozen=True, kw_only=True)
class KEMSBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a KEMS binary sensor."""

    is_on_fn: IsOnFn
    source_key: str | None = None
    source_any_keys: tuple[str, ...] = ()


BINARY_SENSORS: tuple[KEMSBinarySensorEntityDescription, ...] = (
    KEMSBinarySensorEntityDescription(
        key="off_peak",
        name="Off peak",
        icon="mdi:weather-night",
        source_key=CONF_OFF_PEAK,
        is_on_fn=lambda data: data.snapshot.off_peak,
    ),
    KEMSBinarySensorEntityDescription(
        key="intelligent_slot",
        name="Intelligent slot",
        icon="mdi:ev-station",
        source_key=CONF_INTELLIGENT_SLOT,
        is_on_fn=lambda data: data.snapshot.intelligent_slot,
    ),
    KEMSBinarySensorEntityDescription(
        key="cheap_period_confirmed",
        name="Cheap period confirmed",
        icon="mdi:cash-check",
        is_on_fn=lambda data: data.snapshot.cheap_period_confirmed,
    ),
    KEMSBinarySensorEntityDescription(
        key="ev_connected",
        name="EV connected",
        icon="mdi:ev-plug-type2",
        source_any_keys=(CONF_EV_STATUS, CONF_EV_CONNECTED),
        is_on_fn=lambda data: data.snapshot.ev_connected,
    ),
    KEMSBinarySensorEntityDescription(
        key="ev_charging",
        name="EV charging",
        icon="mdi:battery-charging",
        source_any_keys=(CONF_EV_STATUS, CONF_EV_CHARGING),
        is_on_fn=lambda data: data.snapshot.ev_charging,
    ),
    KEMSBinarySensorEntityDescription(
        key="battery_present",
        name="Battery data available",
        icon="mdi:home-battery-outline",
        source_key=CONF_BATTERY_SOC,
        is_on_fn=lambda data: data.snapshot.battery_soc is not None,
    ),
    KEMSBinarySensorEntityDescription(
        key="learning_ready",
        name="Learning ready",
        icon="mdi:brain",
        is_on_fn=lambda data: data.learned.ready,
    ),
    KEMSBinarySensorEntityDescription(
        key="simulation_ready",
        name="Simulation ready",
        icon="mdi:calculator-variant-outline",
        is_on_fn=lambda data: data.simulation.ready,
    ),
    KEMSBinarySensorEntityDescription(
        key="simulated_saving",
        name="Simulation shows a saving",
        icon="mdi:piggy-bank-outline",
        is_on_fn=lambda data: (
            data.simulation.saving_pence is not None
            and data.simulation.saving_pence > 0
        ),
    ),
    KEMSBinarySensorEntityDescription(
        key="day_rate_grid_import",
        name="Grid import outside cheap period",
        icon="mdi:alert-outline",
        is_on_fn=lambda data: (
            data.snapshot.grid_import_kw is not None
            and data.snapshot.grid_import_kw > 0.1
            and not data.snapshot.cheap_period_confirmed
        ),
    ),
)


def _source_is_configured(
    description: KEMSBinarySensorEntityDescription,
    mappings: dict[str, str],
) -> bool:
    """Return whether a binary sensor has configured source data."""
    if description.source_key is None and not description.source_any_keys:
        return True
    if description.source_key in mappings:
        return True
    return any(key in mappings for key in description.source_any_keys)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KEMS binary sensors."""
    coordinator = entry.runtime_data
    mappings = coordinator.entities.as_dict()
    async_add_entities(
        KEMSBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
        if _source_is_configured(description, mappings)
    )


class KEMSBinarySensor(KEMSEntity, BinarySensorEntity):
    """Generic coordinator-backed KEMS binary sensor."""

    entity_description: KEMSBinarySensorEntityDescription

    def __init__(
        self,
        coordinator,
        description: KEMSBinarySensorEntityDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state."""
        return self.entity_description.is_on_fn(self.coordinator.data)
