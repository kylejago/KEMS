"""Sensor platform for KEMS."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
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
    CONF_GAS_COST_TODAY,
    CONF_GAS_CURRENT_RATE,
    CONF_GAS_METER_TOTAL,
    CONF_GAS_STANDING_CHARGE,
    CONF_GAS_USAGE_TODAY,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_HOUSE_LOAD,
    CONF_NEXT_IMPORT_RATE,
    CONF_NEXT_OFFPEAK_START,
    CONF_OFFPEAK_END,
    CONF_SOLAR_POWER,
)
from .entity import KEMSEntity
from .kems_core import FOXHOLE_PROPOSAL_PROFILE, KEMSData

ValueFn = Callable[[KEMSData], Any]
AttributesFn = Callable[[KEMSData], Mapping[str, Any]]
GAS_SOURCE_KEYS = (
    CONF_GAS_CURRENT_RATE,
    CONF_GAS_STANDING_CHARGE,
    CONF_GAS_METER_TOTAL,
    CONF_GAS_USAGE_TODAY,
    CONF_GAS_COST_TODAY,
)


@dataclass(frozen=True, kw_only=True)
class KEMSSensorEntityDescription(SensorEntityDescription):
    """Describe a KEMS sensor."""

    value_fn: ValueFn
    source_key: str | None = None
    source_all_keys: tuple[str, ...] = ()
    source_any_keys: tuple[str, ...] = ()
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
    """Expose the complete proposal simulation comparison."""
    simulation = data.simulation
    return {
        "ready": simulation.ready,
        "samples": simulation.samples,
        "actual_import_cost_pence": simulation.actual_import_cost_pence,
        "actual_export_income_pence": simulation.actual_export_income_pence,
        "simulated_import_cost_pence": simulation.simulated_import_cost_pence,
        "simulated_export_income_pence": simulation.simulated_export_income_pence,
        "actual_grid_import_kwh": simulation.actual_grid_import_kwh,
        "actual_grid_export_kwh": simulation.actual_grid_export_kwh,
        "simulated_grid_import_kwh": simulation.simulated_grid_import_kwh,
        "simulated_grid_export_kwh": simulation.simulated_grid_export_kwh,
        "simulated_solar_generation_kwh": simulation.simulated_solar_generation_kwh,
        "simulated_solar_curtailed_kwh": simulation.simulated_solar_curtailed_kwh,
        "simulated_battery_charge_kwh": simulation.simulated_battery_charge_kwh,
        "simulated_battery_to_home_kwh": simulation.simulated_battery_to_home_kwh,
        "simulated_battery_export_kwh": simulation.simulated_battery_export_kwh,
        "simulated_battery_soc": simulation.simulated_battery_soc,
        "avoided_day_rate_import_kwh": simulation.avoided_day_rate_import_kwh,
        "effective_export_rate_pence": simulation.effective_export_rate_pence,
        "export_limit_kw": simulation.export_limit_kw,
        "proposal_solar_active": simulation.proposal_solar_active,
        "battery_export_enabled": simulation.battery_export_enabled,
        "data_coverage": simulation.data_coverage,
    }


def _gas_attributes(data: KEMSData) -> Mapping[str, Any]:
    """Expose gas aggregation quality and tariff details."""
    return {
        "available": data.gas.available,
        "current_rate_pence": data.gas.current_rate_pence,
        "standing_charge_pence": data.gas.standing_charge_pence,
        "days_observed": data.gas.days_observed,
        "data_coverage": data.gas.data_coverage,
        "typical_daily_usage_kwh": data.gas.typical_daily_usage_kwh,
    }


def _profile_attributes(data: KEMSData) -> Mapping[str, Any]:
    """Expose the proposal system's physical assumptions."""
    profile = FOXHOLE_PROPOSAL_PROFILE
    return {
        "solar_capacity_kwp": profile.solar_capacity_kwp,
        "annual_generation_kwh": profile.annual_generation_kwh,
        "inverter_limit_kw": profile.inverter_limit_kw,
        "battery_capacity_kwh": profile.battery_capacity_kwh,
        "usable_battery_capacity_kwh": profile.usable_battery_capacity_kwh,
        "shading_factor": profile.shading_factor,
        "arrays": [
            {
                "name": array.name,
                "panels": array.panels,
                "capacity_kwp": array.capacity_kwp,
                "azimuth_degrees": array.azimuth_degrees,
                "tilt_degrees": array.tilt_degrees,
            }
            for array in profile.arrays
        ],
        "monthly_generation_kwh": list(profile.monthly_generation_kwh),
    }


def _grid_net(import_kw: float | None, export_kw: float | None) -> float | None:
    """Return signed grid power, positive for import and negative for export."""
    if import_kw is None and export_kw is None:
        return None
    return round((import_kw or 0.0) - (export_kw or 0.0), 3)


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
        key="system_profile",
        name="System profile",
        icon="mdi:solar-power-variant-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: FOXHOLE_PROPOSAL_PROFILE.name,
        attributes_fn=_profile_attributes,
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
        key="simulation_export_rate",
        name="Simulation export rate",
        icon="mdi:cash-plus",
        native_unit_of_measurement="p/kWh",
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.simulation.effective_export_rate_pence,
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
        state_class=SensorStateClass.MEASUREMENT,
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
        state_class=SensorStateClass.MEASUREMENT,
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
        state_class=SensorStateClass.MEASUREMENT,
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
        state_class=SensorStateClass.MEASUREMENT,
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
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        source_key=CONF_GRID_EXPORT,
        value_fn=lambda data: data.snapshot.grid_export_kw,
    ),
    KEMSSensorEntityDescription(
        key="grid_net_power",
        name="Grid net power",
        icon="mdi:transmission-tower",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        source_any_keys=(CONF_GRID_IMPORT, CONF_GRID_EXPORT),
        value_fn=lambda data: _grid_net(
            data.snapshot.grid_import_kw,
            data.snapshot.grid_export_kw,
        ),
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
        name="Observed electricity net cost today",
        icon="mdi:cash-marker",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.actual_cost_pence,
    ),
    KEMSSensorEntityDescription(
        key="simulated_cost_today",
        name="Simulated electricity net cost today",
        icon="mdi:calculator-variant-outline",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.simulated_cost_pence,
        attributes_fn=_simulation_attributes,
    ),
    KEMSSensorEntityDescription(
        key="simulated_saving_today",
        name="Simulated electricity saving today",
        icon="mdi:piggy-bank-outline",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.saving_pence,
    ),
    KEMSSensorEntityDescription(
        key="actual_grid_import_today",
        name="Observed grid import today",
        icon="mdi:transmission-tower-import",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.actual_grid_import_kwh,
    ),
    KEMSSensorEntityDescription(
        key="actual_grid_export_today",
        name="Observed grid export today",
        icon="mdi:transmission-tower-export",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.actual_grid_export_kwh,
    ),
    KEMSSensorEntityDescription(
        key="actual_export_income_today",
        name="Observed export income today",
        icon="mdi:cash-plus",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.actual_export_income_pence,
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
        key="simulated_grid_export_today",
        name="Simulated grid export today",
        icon="mdi:transmission-tower-export",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.simulated_grid_export_kwh,
    ),
    KEMSSensorEntityDescription(
        key="simulated_export_income_today",
        name="Simulated export income today",
        icon="mdi:cash-plus",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.simulated_export_income_pence,
    ),
    KEMSSensorEntityDescription(
        key="simulated_solar_generation_today",
        name="Simulated solar generation today",
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.simulated_solar_generation_kwh,
    ),
    KEMSSensorEntityDescription(
        key="simulated_solar_curtailed_today",
        name="Simulated solar curtailed today",
        icon="mdi:solar-power-variant-outline",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.simulation.simulated_solar_curtailed_kwh,
    ),
    KEMSSensorEntityDescription(
        key="simulated_battery_charge_today",
        name="Simulated battery charged today",
        icon="mdi:battery-arrow-up-outline",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.simulated_battery_charge_kwh,
    ),
    KEMSSensorEntityDescription(
        key="simulated_battery_to_home_today",
        name="Simulated battery to home today",
        icon="mdi:home-battery-outline",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.simulated_battery_to_home_kwh,
    ),
    KEMSSensorEntityDescription(
        key="simulated_battery_export_today",
        name="Simulated battery export today",
        icon="mdi:battery-arrow-down-outline",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.simulated_battery_export_kwh,
    ),
    KEMSSensorEntityDescription(
        key="simulated_battery_soc",
        name="Simulated battery state of charge",
        icon="mdi:battery-sync-outline",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda data: data.simulation.simulated_battery_soc,
    ),
    KEMSSensorEntityDescription(
        key="avoided_day_rate_import_today",
        name="Avoided day-rate import today",
        icon="mdi:transmission-tower-off",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.avoided_day_rate_import_kwh,
    ),
    KEMSSensorEntityDescription(
        key="simulated_house_load_power",
        name="Simulated house load power",
        icon="mdi:home-lightning-bolt-outline",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.current_simulated_house_load_kw,
    ),
    KEMSSensorEntityDescription(
        key="simulated_solar_power",
        name="Simulated solar power",
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.current_simulated_solar_power_kw,
    ),
    KEMSSensorEntityDescription(
        key="simulated_grid_import_power",
        name="Simulated grid import power",
        icon="mdi:transmission-tower-import",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.current_simulated_grid_import_kw,
    ),
    KEMSSensorEntityDescription(
        key="simulated_grid_export_power",
        name="Simulated grid export power",
        icon="mdi:transmission-tower-export",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.current_simulated_grid_export_kw,
    ),
    KEMSSensorEntityDescription(
        key="simulated_grid_net_power",
        name="Simulated grid net power",
        icon="mdi:transmission-tower",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: _grid_net(
            data.simulation.current_simulated_grid_import_kw,
            data.simulation.current_simulated_grid_export_kw,
        ),
    ),
    KEMSSensorEntityDescription(
        key="simulated_battery_power",
        name="Simulated battery power",
        icon="mdi:battery-sync-outline",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.current_simulated_battery_power_kw,
    ),
    KEMSSensorEntityDescription(
        key="proposal_solar_daily_target",
        name="Proposal solar target today",
        icon="mdi:weather-sunny",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: FOXHOLE_PROPOSAL_PROFILE.daily_generation_target_kwh(
            data.snapshot.timestamp
        ),
    ),
    KEMSSensorEntityDescription(
        key="gas_current_rate",
        name="Gas current rate",
        icon="mdi:cash",
        native_unit_of_measurement="p/kWh",
        suggested_display_precision=2,
        source_any_keys=GAS_SOURCE_KEYS,
        value_fn=lambda data: data.gas.current_rate_pence,
        attributes_fn=_gas_attributes,
    ),
    KEMSSensorEntityDescription(
        key="gas_standing_charge",
        name="Gas standing charge",
        icon="mdi:cash-clock",
        native_unit_of_measurement="p/day",
        suggested_display_precision=2,
        source_any_keys=GAS_SOURCE_KEYS,
        value_fn=lambda data: data.gas.standing_charge_pence,
    ),
    KEMSSensorEntityDescription(
        key="gas_usage_today",
        name="Gas usage today",
        icon="mdi:fire",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        source_any_keys=GAS_SOURCE_KEYS,
        value_fn=lambda data: data.gas.usage_today_kwh,
    ),
    KEMSSensorEntityDescription(
        key="gas_cost_today",
        name="Gas cost today",
        icon="mdi:cash-marker",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        source_any_keys=GAS_SOURCE_KEYS,
        value_fn=lambda data: data.gas.cost_today_pence,
    ),
    KEMSSensorEntityDescription(
        key="gas_usage_month",
        name="Gas usage this month",
        icon="mdi:fire-circle",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        source_any_keys=GAS_SOURCE_KEYS,
        value_fn=lambda data: data.gas.usage_month_kwh,
    ),
    KEMSSensorEntityDescription(
        key="gas_cost_month",
        name="Gas cost this month",
        icon="mdi:calendar-cash",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        source_any_keys=GAS_SOURCE_KEYS,
        value_fn=lambda data: data.gas.cost_month_pence,
    ),
    KEMSSensorEntityDescription(
        key="typical_gas_usage",
        name="Typical daily gas usage",
        icon="mdi:chart-bell-curve-cumulative",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        source_any_keys=GAS_SOURCE_KEYS,
        value_fn=lambda data: data.gas.typical_daily_usage_kwh,
    ),
    KEMSSensorEntityDescription(
        key="whole_home_observed_cost_today",
        name="Whole-home observed cost today",
        icon="mdi:home-currency-gbp",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.whole_home.observed_total_cost_pence,
    ),
    KEMSSensorEntityDescription(
        key="whole_home_simulated_cost_today",
        name="Whole-home simulated cost today",
        icon="mdi:home-lightning-bolt-outline",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.whole_home.simulated_total_cost_pence,
    ),
    KEMSSensorEntityDescription(
        key="whole_home_simulated_saving_today",
        name="Whole-home simulated saving today",
        icon="mdi:home-plus-outline",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.whole_home.simulated_saving_pence,
    ),
    KEMSSensorEntityDescription(
        key="whole_home_energy_today",
        name="Whole-home energy today",
        icon="mdi:home-lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: data.whole_home.observed_total_energy_kwh,
    ),
    KEMSSensorEntityDescription(
        key="gas_energy_share",
        name="Gas share of whole-home energy",
        icon="mdi:chart-donut",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        source_any_keys=GAS_SOURCE_KEYS,
        value_fn=lambda data: data.whole_home.gas_energy_share_percent,
    ),
)


def _source_is_configured(
    description: KEMSSensorEntityDescription,
    mappings: dict[str, str],
) -> bool:
    """Return whether a sensor has enough configured source data."""
    if (
        description.source_key is None
        and not description.source_all_keys
        and not description.source_any_keys
    ):
        return True
    if description.source_key in mappings:
        return True
    if description.source_any_keys and any(
        key in mappings for key in description.source_any_keys
    ):
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
