"""Sensor platform for KEMS."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_BATTERY_CURRENT,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_VOLTAGE,
    CONF_CURRENT_EXPORT_RATE,
    CONF_CURRENT_IMPORT_RATE,
    CONF_EV_POWER,
    CONF_EV_SOC,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_HOUSE_LOAD,
    CONF_NEXT_IMPORT_RATE,
    CONF_NEXT_OFFPEAK_START,
    CONF_OFFPEAK_END,
    CONF_SOLAR_POWER,
)
from .entity import KEMSEntity
from .kems_core import KEMSData

ValueFn = Callable[[KEMSData], Any]
AttributesFn = Callable[[KEMSData], Mapping[str, Any]]


@dataclass(frozen=True, kw_only=True)
class KEMSSensorEntityDescription(SensorEntityDescription):
    """Describe a KEMS sensor."""

    value_fn: ValueFn
    source_key: str | None = None
    source_all_keys: tuple[str, ...] = ()
    attributes_fn: AttributesFn | None = None


def _advice_attributes(data: KEMSData) -> Mapping[str, Any]:
    """Expose explainable advice details."""
    return {
        "code": data.advice.primary.code,
        "message": data.advice.primary.message,
        "priority": data.advice.primary.priority,
        "confidence": data.advice.primary.confidence,
        "estimated_saving_pence": data.advice.primary.estimated_saving_pence,
        "recommendations": [item.to_dict() for item in data.advice.items],
    }


def _simulation_attributes(data: KEMSData) -> Mapping[str, Any]:
    """Expose the complete simulation comparison."""
    simulation = data.simulation
    return {
        "ready": simulation.ready,
        "samples": simulation.samples,
        "actual_grid_import_kwh": simulation.actual_grid_import_kwh,
        "simulated_grid_import_kwh": simulation.simulated_grid_import_kwh,
        "simulated_grid_export_kwh": simulation.simulated_grid_export_kwh,
        "simulated_battery_soc": simulation.simulated_battery_soc,
        "avoided_day_rate_import_kwh": simulation.avoided_day_rate_import_kwh,
        "data_coverage": simulation.data_coverage,
    }


SENSORS: tuple[KEMSSensorEntityDescription, ...] = (
    KEMSSensorEntityDescription(
        key="status",
        name="Status",
        icon="mdi:home-lightning-bolt",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: "Active",
    ),
    KEMSSensorEntityDescription(
        key="phase",
        name="Phase",
        icon="mdi:transit-connection-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.phase,
    ),
    KEMSSensorEntityDescription(
        key="data_quality",
        name="Data quality",
        icon="mdi:database-check-outline",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.quality.score,
        attributes_fn=lambda data: {
            "configured_sources": data.quality.configured,
            "available_sources": data.quality.available,
            "missing_fields": list(data.quality.missing_fields),
        },
    ),
    KEMSSensorEntityDescription(
        key="history_samples",
        name="History samples",
        icon="mdi:database-clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.history_samples,
    ),
    KEMSSensorEntityDescription(
        key="current_import_rate",
        name="Current import rate",
        icon="mdi:cash",
        native_unit_of_measurement="p/kWh",
        suggested_display_precision=2,
        source_key=CONF_CURRENT_IMPORT_RATE,
        value_fn=lambda data: data.snapshot.current_import_rate,
    ),
    KEMSSensorEntityDescription(
        key="next_import_rate",
        name="Next import rate",
        icon="mdi:cash-clock",
        native_unit_of_measurement="p/kWh",
        suggested_display_precision=2,
        source_key=CONF_NEXT_IMPORT_RATE,
        value_fn=lambda data: data.snapshot.next_import_rate,
    ),
    KEMSSensorEntityDescription(
        key="current_export_rate",
        name="Current export rate",
        icon="mdi:cash-plus",
        native_unit_of_measurement="p/kWh",
        suggested_display_precision=2,
        source_key=CONF_CURRENT_EXPORT_RATE,
        value_fn=lambda data: data.snapshot.current_export_rate,
    ),
    KEMSSensorEntityDescription(
        key="next_offpeak_start",
        name="Next off-peak start",
        device_class=SensorDeviceClass.TIMESTAMP,
        source_key=CONF_NEXT_OFFPEAK_START,
        value_fn=lambda data: data.snapshot.next_offpeak_start,
    ),
    KEMSSensorEntityDescription(
        key="offpeak_end",
        name="Off-peak end",
        device_class=SensorDeviceClass.TIMESTAMP,
        source_key=CONF_OFFPEAK_END,
        value_fn=lambda data: data.snapshot.offpeak_end,
    ),
    KEMSSensorEntityDescription(
        key="ev_power",
        name="EV charging power",
        icon="mdi:ev-station",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        source_key=CONF_EV_POWER,
        value_fn=lambda data: data.snapshot.ev_power_kw,
    ),
    KEMSSensorEntityDescription(
        key="ev_soc",
        name="EV state of charge",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        source_key=CONF_EV_SOC,
        value_fn=lambda data: data.snapshot.ev_soc,
    ),
    KEMSSensorEntityDescription(
        key="house_load",
        name="House load",
        icon="mdi:home-lightning-bolt-outline",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        source_key=CONF_HOUSE_LOAD,
        value_fn=lambda data: data.snapshot.house_load_kw,
    ),
    KEMSSensorEntityDescription(
        key="battery_soc",
        name="Battery state of charge",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        source_key=CONF_BATTERY_SOC,
        value_fn=lambda data: data.snapshot.battery_soc,
    ),
    KEMSSensorEntityDescription(
        key="battery_power",
        name="Battery power",
        icon="mdi:battery-charging-medium",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        source_key=CONF_BATTERY_POWER,
        source_all_keys=(CONF_BATTERY_VOLTAGE, CONF_BATTERY_CURRENT),
        value_fn=lambda data: data.snapshot.battery_power_kw,
    ),
    KEMSSensorEntityDescription(
        key="solar_power",
        name="Solar power",
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        source_key=CONF_SOLAR_POWER,
        value_fn=lambda data: data.snapshot.solar_power_kw,
    ),
    KEMSSensorEntityDescription(
        key="grid_import",
        name="Grid import",
        icon="mdi:transmission-tower-import",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        source_key=CONF_GRID_IMPORT,
        value_fn=lambda data: data.snapshot.grid_import_kw,
    ),
    KEMSSensorEntityDescription(
        key="grid_export",
        name="Grid export",
        icon="mdi:transmission-tower-export",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        source_key=CONF_GRID_EXPORT,
        value_fn=lambda data: data.snapshot.grid_export_kw,
    ),
    KEMSSensorEntityDescription(
        key="learning_confidence",
        name="Learning confidence",
        icon="mdi:brain",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda data: data.learned.confidence,
        attributes_fn=lambda data: {
            "days_observed": data.learned.days_observed,
            "samples": data.learned.samples,
            "profile_slots": data.learned.profile_slots,
            "ready": data.learned.ready,
        },
    ),
    KEMSSensorEntityDescription(
        key="typical_house_load",
        name="Typical house load now",
        icon="mdi:chart-bell-curve-cumulative",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.learned.typical_house_load_kw,
    ),
    KEMSSensorEntityDescription(
        key="typical_solar_power",
        name="Typical solar power now",
        icon="mdi:white-balance-sunny",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.learned.typical_solar_power_kw,
    ),
    KEMSSensorEntityDescription(
        key="predicted_energy_until_offpeak",
        name="Predicted energy until off-peak",
        icon="mdi:home-clock-outline",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.learned.predicted_energy_until_offpeak_kwh,
    ),
    KEMSSensorEntityDescription(
        key="advice",
        name="Advice",
        icon="mdi:lightbulb-on-outline",
        value_fn=lambda data: data.advice.primary.title,
        attributes_fn=_advice_attributes,
    ),
    KEMSSensorEntityDescription(
        key="actual_cost_today",
        name="Observed cost today",
        icon="mdi:cash-marker",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.actual_cost_pence,
    ),
    KEMSSensorEntityDescription(
        key="simulated_cost_today",
        name="Simulated KEMS cost today",
        icon="mdi:calculator-variant-outline",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.simulated_cost_pence,
        attributes_fn=_simulation_attributes,
    ),
    KEMSSensorEntityDescription(
        key="simulated_saving_today",
        name="Simulated saving today",
        icon="mdi:piggy-bank-outline",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.saving_pence,
    ),
    KEMSSensorEntityDescription(
        key="simulated_grid_import_today",
        name="Simulated grid import today",
        icon="mdi:transmission-tower-import",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.simulated_grid_import_kwh,
    ),
    KEMSSensorEntityDescription(
        key="simulated_battery_soc",
        name="Simulated battery state of charge",
        icon="mdi:battery-sync-outline",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda data: data.simulation.simulated_battery_soc,
    ),
)


def _source_is_configured(
    description: KEMSSensorEntityDescription,
    mappings: dict[str, str],
) -> bool:
    """Return whether a sensor has enough configured source data."""
    if description.source_key is None and not description.source_all_keys:
        return True
    if description.source_key in mappings:
        return True
    return bool(
        description.source_all_keys
        and all(key in mappings for key in description.source_all_keys)
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KEMS sensors."""
    coordinator = entry.runtime_data
    mappings = coordinator.entities.as_dict()
    async_add_entities(
        KEMSSensor(coordinator, description)
        for description in SENSORS
        if _source_is_configured(description, mappings)
    )


class KEMSSensor(KEMSEntity, SensorEntity):
    """Generic coordinator-backed KEMS sensor."""

    entity_description: KEMSSensorEntityDescription

    def __init__(
        self,
        coordinator,
        description: KEMSSensorEntityDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return explainability or diagnostic attributes."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
