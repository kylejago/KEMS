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
        "actual_house_consumption_kwh": simulation.actual_house_consumption_kwh,
        "actual_ev_energy_kwh": simulation.actual_ev_energy_kwh,
        "actual_solar_generation_kwh": simulation.actual_solar_generation_kwh,
        "actual_battery_charge_kwh": simulation.actual_battery_charge_kwh,
        "actual_battery_discharge_kwh": simulation.actual_battery_discharge_kwh,
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
        "current_simulated_battery_to_home_power_kw": (
            simulation.current_simulated_battery_to_home_power_kw
        ),
        "current_simulated_battery_export_power_kw": (
            simulation.current_simulated_battery_export_power_kw
        ),
        "target_battery_export_power_kw": (simulation.target_battery_export_power_kw),
        "exportable_battery_energy_kwh": (simulation.exportable_battery_energy_kwh),
        "reserved_for_home_kwh": simulation.reserved_for_home_kwh,
        "hours_until_next_cheap_period": (simulation.hours_until_next_cheap_period),
        "projected_soc_at_cheap_period_percent": (
            simulation.projected_soc_at_cheap_period_percent
        ),
        "home_reserve_forecast_source": (simulation.home_reserve_forecast_source),
        "projected_grid_import_before_cheap_kwh": (
            simulation.projected_grid_import_before_cheap_kwh
        ),
        "battery_export_paused_for_home_reserve": (
            simulation.battery_export_paused_for_home_reserve
        ),
        "saving_session_joined": simulation.saving_session_joined,
        "saving_session_active": simulation.saving_session_active,
        "saving_session_start": simulation.saving_session_start,
        "saving_session_end": simulation.saving_session_end,
        "saving_session_duration_minutes": (simulation.saving_session_duration_minutes),
        "saving_session_octopoints_per_kwh": (
            simulation.saving_session_octopoints_per_kwh
        ),
        "saving_session_bonus_rate_pence": (simulation.saving_session_bonus_rate_pence),
        "saving_session_baseline_net_kwh": (simulation.saving_session_baseline_net_kwh),
        "saving_session_baseline_source": (simulation.saving_session_baseline_source),
        "saving_session_baseline_incomplete": (
            simulation.saving_session_baseline_incomplete
        ),
        "saving_session_battery_reserve_kwh": (
            simulation.saving_session_battery_reserve_kwh
        ),
        "saving_session_export_target_kw": (simulation.saving_session_export_target_kw),
        "estimated_saving_session_export_kwh": (
            simulation.estimated_saving_session_export_kwh
        ),
        "estimated_saving_session_rewardable_reduction_kwh": (
            simulation.estimated_saving_session_rewardable_reduction_kwh
        ),
        "estimated_saving_session_bonus_pence": (
            simulation.estimated_saving_session_bonus_pence
        ),
        "estimated_saving_session_export_income_pence": (
            simulation.estimated_saving_session_export_income_pence
        ),
        "estimated_saving_session_total_income_pence": (
            simulation.estimated_saving_session_total_income_pence
        ),
        "simulated_saving_session_bonus_pence": (
            simulation.simulated_saving_session_bonus_pence
        ),
        "battery_reserved_for_saving_session": (
            simulation.battery_reserved_for_saving_session
        ),
        "battery_export_reduced_for_saving_session": (
            simulation.battery_export_reduced_for_saving_session
        ),
        "avoided_day_rate_import_kwh": simulation.avoided_day_rate_import_kwh,
        "baseline_no_system_cost_pence": simulation.baseline_no_system_cost_pence,
        "actual_avoided_import_value_pence": (
            simulation.actual_avoided_import_value_pence
        ),
        "simulated_avoided_import_value_pence": (
            simulation.simulated_avoided_import_value_pence
        ),
        "actual_system_value_pence": simulation.actual_system_value_pence,
        "simulated_system_value_pence": simulation.simulated_system_value_pence,
        "effective_export_rate_pence": simulation.effective_export_rate_pence,
        "inverter_limit_kw": simulation.inverter_limit_kw,
        "export_limit_kw": simulation.export_limit_kw,
        "strategy": simulation.strategy,
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


def _roi_attributes(data: KEMSData) -> Mapping[str, Any]:
    """Expose transparent ROI assumptions and proposal benchmarks."""
    roi = data.roi
    return {
        "ready": roi.ready,
        "system_installed": roi.system_installed,
        "system_paid_back": roi.system_paid_back,
        "net_investment_gbp": roi.net_investment_gbp,
        "proposal_annual_saving_gbp": roi.proposal_annual_saving_gbp,
        "proposal_payback_years": roi.proposal_payback_years,
        "proposal_lifetime_savings_gbp": roi.proposal_lifetime_savings_gbp,
        "proposal_net_savings_gbp": roi.proposal_net_savings_gbp,
        "observed_days": roi.observed_days,
        "operating_days": roi.operating_days,
        "confidence": roi.confidence,
    }


def _lifetime_attributes(data: KEMSData) -> Mapping[str, Any]:
    """Expose best-day and permanent-ledger metadata."""
    ledger = data.lifetime
    return {
        "first_observation": (
            ledger.first_observation.isoformat() if ledger.first_observation else None
        ),
        "last_updated": (
            ledger.last_updated.isoformat() if ledger.last_updated else None
        ),
        "commissioning_date": (
            ledger.commissioning_date.isoformat() if ledger.commissioning_date else None
        ),
        "paid_back_date": (
            ledger.paid_back_date.isoformat() if ledger.paid_back_date else None
        ),
        "best_system_value_day": (
            ledger.best_system_value_day.isoformat()
            if ledger.best_system_value_day
            else None
        ),
        "best_system_value_day_gbp": round(
            ledger.best_system_value_day_pence / 100,
            2,
        ),
        "best_solar_day": (
            ledger.best_solar_day.isoformat() if ledger.best_solar_day else None
        ),
        "best_solar_day_kwh": round(ledger.best_solar_day_kwh, 3),
        "best_export_day": (
            ledger.best_export_day.isoformat() if ledger.best_export_day else None
        ),
        "best_export_day_kwh": round(ledger.best_export_day_kwh, 3),
    }


def _lifetime_total_cost_gbp(data: KEMSData) -> float:
    """Return imported electricity plus gas minus export earnings."""
    ledger = data.lifetime
    return round(
        (ledger.import_cost_pence + ledger.gas_cost_pence - ledger.export_income_pence)
        / 100,
        2,
    )


def _lifetime_total_energy_kwh(data: KEMSData) -> float:
    """Return all observed household electricity and gas energy."""
    return round(
        data.lifetime.house_consumption_kwh + data.lifetime.gas_consumption_kwh,
        3,
    )


def _lifetime_grid_independence(data: KEMSData) -> float | None:
    """Return the share of household electricity not supplied by grid import."""
    house = data.lifetime.house_consumption_kwh
    if house <= 0:
        return None
    return round(100 * max(house - data.lifetime.grid_import_kwh, 0.0) / house, 1)


def _estimated_battery_cycles(data: KEMSData) -> float | None:
    """Estimate equivalent full cycles from recorded battery discharge."""
    usable = FOXHOLE_PROPOSAL_PROFILE.usable_battery_capacity_kwh
    if usable <= 0:
        return None
    return round(data.lifetime.battery_discharge_kwh / usable, 2)


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


def _grid_direction(import_kw: float | None, export_kw: float | None) -> str:
    """Return a clear text direction for the normalised grid flow."""
    net = _grid_net(import_kw, export_kw)
    if net is None:
        return "Unknown"
    if net > 0.01:
        return "Importing"
    if net < -0.01:
        return "Exporting"
    return "Neutral"


def _grid_attributes(data: KEMSData) -> Mapping[str, Any]:
    """Explain raw and normalised grid values."""
    snapshot = data.snapshot
    return {
        "sign_convention": "positive = import, negative = export",
        "direction": _grid_direction(
            snapshot.grid_import_kw,
            snapshot.grid_export_kw,
        ),
        "normalisation_mode": snapshot.grid_flow_mode,
        "raw_import_source_kw": snapshot.raw_grid_import_kw,
        "raw_export_source_kw": snapshot.raw_grid_export_kw,
        "normalised_import_kw": snapshot.grid_import_kw,
        "normalised_export_kw": snapshot.grid_export_kw,
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
        attributes_fn=_grid_attributes,
    ),
    KEMSSensorEntityDescription(
        key="grid_flow_direction",
        name="Grid flow direction",
        icon="mdi:swap-horizontal",
        entity_category=EntityCategory.DIAGNOSTIC,
        source_any_keys=(CONF_GRID_IMPORT, CONF_GRID_EXPORT),
        value_fn=lambda data: _grid_direction(
            data.snapshot.grid_import_kw,
            data.snapshot.grid_export_kw,
        ),
        attributes_fn=_grid_attributes,
    ),
    KEMSSensorEntityDescription(
        key="grid_normalisation_mode",
        name="Grid normalisation mode",
        icon="mdi:tune-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        source_any_keys=(CONF_GRID_IMPORT, CONF_GRID_EXPORT),
        value_fn=lambda data: data.snapshot.grid_flow_mode,
        attributes_fn=_grid_attributes,
    ),
    KEMSSensorEntityDescription(
        key="raw_grid_import_source",
        name="Raw grid import source",
        icon="mdi:code-tags",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=3,
        source_key=CONF_GRID_IMPORT,
        value_fn=lambda data: data.snapshot.raw_grid_import_kw,
    ),
    KEMSSensorEntityDescription(
        key="raw_grid_export_source",
        name="Raw grid export source",
        icon="mdi:code-tags",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=3,
        source_key=CONF_GRID_EXPORT,
        value_fn=lambda data: data.snapshot.raw_grid_export_kw,
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
            "elapsed_observation_days": data.learned.elapsed_observation_days,
            "samples": data.learned.samples,
            "data_coverage": data.learned.data_coverage,
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
        key="simulated_battery_to_home_power",
        name="Simulated battery to home power",
        icon="mdi:home-battery-outline",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: (
            data.simulation.current_simulated_battery_to_home_power_kw
        ),
    ),
    KEMSSensorEntityDescription(
        key="simulated_battery_export_power",
        name="Simulated battery export power",
        icon="mdi:battery-arrow-up-outline",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: (
            data.simulation.current_simulated_battery_export_power_kw
        ),
    ),
    KEMSSensorEntityDescription(
        key="target_battery_export_power",
        name="Target battery export power",
        icon="mdi:battery-clock-outline",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.target_battery_export_power_kw,
        attributes_fn=_simulation_attributes,
    ),
    KEMSSensorEntityDescription(
        key="exportable_battery_energy",
        name="Exportable battery energy remaining",
        icon="mdi:battery-arrow-down-outline",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.exportable_battery_energy_kwh,
    ),
    KEMSSensorEntityDescription(
        key="battery_energy_reserved_for_home",
        name="Battery energy reserved for home",
        icon="mdi:home-battery-outline",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.reserved_for_home_kwh,
    ),
    KEMSSensorEntityDescription(
        key="hours_until_next_cheap_period",
        name="Hours until next cheap period",
        icon="mdi:clock-fast",
        native_unit_of_measurement="h",
        suggested_display_precision=1,
        value_fn=lambda data: data.simulation.hours_until_next_cheap_period,
    ),
    KEMSSensorEntityDescription(
        key="projected_soc_at_cheap_period",
        name="Projected SOC at cheap-period start",
        icon="mdi:battery-clock",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda data: (data.simulation.projected_soc_at_cheap_period_percent),
    ),
    KEMSSensorEntityDescription(
        key="home_reserve_forecast_source",
        name="Home reserve forecast source",
        icon="mdi:home-clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.simulation.home_reserve_forecast_source,
    ),
    KEMSSensorEntityDescription(
        key="projected_grid_import_before_cheap",
        name="Projected grid import before cheap period",
        icon="mdi:transmission-tower-import",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: (data.simulation.projected_grid_import_before_cheap_kwh),
    ),
    KEMSSensorEntityDescription(
        key="next_saving_session_start",
        name="Next Power Down session start",
        icon="mdi:calendar-start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.simulation.saving_session_start,
    ),
    KEMSSensorEntityDescription(
        key="next_saving_session_end",
        name="Next Power Down session end",
        icon="mdi:calendar-end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.simulation.saving_session_end,
    ),
    KEMSSensorEntityDescription(
        key="saving_session_duration",
        name="Power Down session duration",
        icon="mdi:timer-outline",
        native_unit_of_measurement="min",
        suggested_display_precision=0,
        value_fn=lambda data: data.simulation.saving_session_duration_minutes,
    ),
    KEMSSensorEntityDescription(
        key="saving_session_octopoints_per_kwh",
        name="Power Down session Octopoints per kWh",
        icon="mdi:octagram-outline",
        native_unit_of_measurement="points/kWh",
        suggested_display_precision=0,
        value_fn=lambda data: data.simulation.saving_session_octopoints_per_kwh,
    ),
    KEMSSensorEntityDescription(
        key="saving_session_bonus_rate",
        name="Power Down session bonus rate",
        icon="mdi:cash-plus",
        native_unit_of_measurement="p/kWh",
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.saving_session_bonus_rate_pence,
    ),
    KEMSSensorEntityDescription(
        key="saving_session_baseline_net_energy",
        name="Power Down session baseline net energy",
        icon="mdi:chart-bell-curve-cumulative",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=3,
        value_fn=lambda data: data.simulation.saving_session_baseline_net_kwh,
    ),
    KEMSSensorEntityDescription(
        key="saving_session_baseline_source",
        name="Power Down session baseline source",
        icon="mdi:database-search-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.simulation.saving_session_baseline_source,
    ),
    KEMSSensorEntityDescription(
        key="saving_session_battery_reserve",
        name="Power Down session battery reserve",
        icon="mdi:battery-lock",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.saving_session_battery_reserve_kwh,
    ),
    KEMSSensorEntityDescription(
        key="saving_session_export_target",
        name="Power Down session export target",
        icon="mdi:transmission-tower-export",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.saving_session_export_target_kw,
    ),
    KEMSSensorEntityDescription(
        key="estimated_saving_session_export",
        name="Estimated Power Down session export",
        icon="mdi:transmission-tower-export",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.estimated_saving_session_export_kwh,
    ),
    KEMSSensorEntityDescription(
        key="estimated_saving_session_reduction",
        name="Estimated Power Down session rewardable reduction",
        icon="mdi:chart-line-variant",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: (
            data.simulation.estimated_saving_session_rewardable_reduction_kwh
        ),
    ),
    KEMSSensorEntityDescription(
        key="estimated_saving_session_bonus",
        name="Estimated Power Down session bonus",
        icon="mdi:cash-star",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.estimated_saving_session_bonus_pence,
    ),
    KEMSSensorEntityDescription(
        key="estimated_saving_session_export_income",
        name="Estimated Power Down session export income",
        icon="mdi:cash-plus",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: (
            data.simulation.estimated_saving_session_export_income_pence
        ),
    ),
    KEMSSensorEntityDescription(
        key="estimated_saving_session_total_income",
        name="Estimated Power Down session total income",
        icon="mdi:cash-multiple",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: (
            data.simulation.estimated_saving_session_total_income_pence
        ),
    ),
    KEMSSensorEntityDescription(
        key="simulated_saving_session_bonus_today",
        name="Simulated Power Down session bonus today",
        icon="mdi:cash-fast",
        native_unit_of_measurement="p",
        suggested_display_precision=2,
        value_fn=lambda data: data.simulation.simulated_saving_session_bonus_pence,
    ),
    KEMSSensorEntityDescription(
        key="simulation_strategy",
        name="Simulation strategy",
        icon="mdi:chart-timeline-variant-shimmer",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.simulation.strategy,
        attributes_fn=_simulation_attributes,
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
    KEMSSensorEntityDescription(
        key="roi_status",
        name="ROI status",
        icon="mdi:finance",
        value_fn=lambda data: data.roi.status,
        attributes_fn=_roi_attributes,
    ),
    KEMSSensorEntityDescription(
        key="system_investment",
        name="System investment",
        icon="mdi:cash-multiple",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        suggested_display_precision=2,
        value_fn=lambda data: data.roi.net_investment_gbp,
    ),
    KEMSSensorEntityDescription(
        key="predicted_annual_saving",
        name="Predicted annual saving",
        icon="mdi:chart-line",
        native_unit_of_measurement="GBP/year",
        suggested_display_precision=2,
        value_fn=lambda data: data.roi.predicted_annual_saving_gbp,
        attributes_fn=_roi_attributes,
    ),
    KEMSSensorEntityDescription(
        key="predicted_payback_years",
        name="Predicted payback",
        icon="mdi:calendar-clock",
        native_unit_of_measurement="years",
        suggested_display_precision=2,
        value_fn=lambda data: data.roi.predicted_payback_years,
    ),
    KEMSSensorEntityDescription(
        key="predicted_payback_date",
        name="Predicted payback date",
        icon="mdi:calendar-check",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.roi.predicted_payback_date,
    ),
    KEMSSensorEntityDescription(
        key="predicted_net_value",
        name="Predicted net value",
        icon="mdi:cash-fast",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        suggested_display_precision=2,
        value_fn=lambda data: data.roi.predicted_net_value_gbp,
    ),
    KEMSSensorEntityDescription(
        key="proposal_annual_saving_benchmark",
        name="Proposal annual saving benchmark",
        icon="mdi:file-chart-outline",
        native_unit_of_measurement="GBP/year",
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.roi.proposal_annual_saving_gbp,
    ),
    KEMSSensorEntityDescription(
        key="proposal_payback_benchmark",
        name="Proposal payback benchmark",
        icon="mdi:file-clock-outline",
        native_unit_of_measurement="years",
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.roi.proposal_payback_years,
    ),
    KEMSSensorEntityDescription(
        key="proposal_net_savings_benchmark",
        name="Proposal net savings benchmark",
        icon="mdi:file-cash-outline",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.roi.proposal_net_savings_gbp,
    ),
    KEMSSensorEntityDescription(
        key="roi_confidence",
        name="ROI confidence",
        icon="mdi:shield-check-outline",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda data: data.roi.confidence,
    ),
    KEMSSensorEntityDescription(
        key="actual_value_created_today",
        name="Actual system value today",
        icon="mdi:cash-plus",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        suggested_display_precision=2,
        value_fn=lambda data: data.roi.actual_value_created_today_gbp,
    ),
    KEMSSensorEntityDescription(
        key="actual_value_created_total",
        name="Actual system value total",
        icon="mdi:piggy-bank",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: data.roi.actual_value_created_total_gbp,
        attributes_fn=_lifetime_attributes,
    ),
    KEMSSensorEntityDescription(
        key="actual_roi_percentage",
        name="Actual ROI",
        icon="mdi:battery-charging-100",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value_fn=lambda data: data.roi.actual_roi_percent,
    ),
    KEMSSensorEntityDescription(
        key="actual_payback_remaining",
        name="Actual payback remaining",
        icon="mdi:cash-clock",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        suggested_display_precision=2,
        value_fn=lambda data: data.roi.actual_payback_remaining_gbp,
    ),
    KEMSSensorEntityDescription(
        key="actual_payback_date",
        name="Actual payback date",
        icon="mdi:calendar-star",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.roi.actual_payback_date,
    ),
    KEMSSensorEntityDescription(
        key="actual_net_profit",
        name="Profit after payback",
        icon="mdi:trending-up",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: data.roi.actual_net_profit_gbp,
    ),
    KEMSSensorEntityDescription(
        key="system_operating_costs",
        name="System operating costs",
        icon="mdi:tools",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: data.roi.operating_costs_gbp,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_observed_days",
        name="Lifetime observed days",
        icon="mdi:calendar-range",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.lifetime.observed_days,
        attributes_fn=_lifetime_attributes,
    ),
    KEMSSensorEntityDescription(
        key="system_operating_days",
        name="System operating days",
        icon="mdi:calendar-heart",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.lifetime.system_operating_days,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_house_consumption",
        name="Lifetime house electricity",
        icon="mdi:home-lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: data.lifetime.house_consumption_kwh,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_ev_energy",
        name="Lifetime EV charging",
        icon="mdi:ev-station",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: data.lifetime.ev_energy_kwh,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_grid_import",
        name="Lifetime grid import",
        icon="mdi:transmission-tower-import",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: data.lifetime.grid_import_kwh,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_grid_export",
        name="Lifetime grid export",
        icon="mdi:transmission-tower-export",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: data.lifetime.grid_export_kwh,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_solar_generation",
        name="Lifetime solar generation",
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: data.lifetime.solar_generation_kwh,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_battery_charge",
        name="Lifetime battery charge",
        icon="mdi:battery-arrow-up-outline",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: data.lifetime.battery_charge_kwh,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_battery_discharge",
        name="Lifetime battery discharge",
        icon="mdi:battery-arrow-down-outline",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: data.lifetime.battery_discharge_kwh,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_gas_consumption",
        name="Lifetime gas consumption",
        icon="mdi:fire",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: data.lifetime.gas_consumption_kwh,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_total_home_energy",
        name="Lifetime whole-home energy",
        icon="mdi:home-lightning-bolt",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=_lifetime_total_energy_kwh,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_import_cost",
        name="Lifetime import cost",
        icon="mdi:cash-minus",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: round(data.lifetime.import_cost_pence / 100, 2),
    ),
    KEMSSensorEntityDescription(
        key="lifetime_export_income",
        name="Lifetime export income",
        icon="mdi:cash-plus",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: round(data.lifetime.export_income_pence / 100, 2),
    ),
    KEMSSensorEntityDescription(
        key="lifetime_gas_cost",
        name="Lifetime gas cost",
        icon="mdi:fire-circle",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: round(data.lifetime.gas_cost_pence / 100, 2),
    ),
    KEMSSensorEntityDescription(
        key="lifetime_avoided_import_value",
        name="Lifetime avoided import value",
        icon="mdi:transmission-tower-off",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: round(
            data.lifetime.actual_avoided_import_value_pence / 100,
            2,
        ),
    ),
    KEMSSensorEntityDescription(
        key="lifetime_system_value",
        name="Lifetime system value",
        icon="mdi:piggy-bank",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: round(data.lifetime.actual_system_value_pence / 100, 2),
    ),
    KEMSSensorEntityDescription(
        key="lifetime_simulated_system_value",
        name="Lifetime simulated system value",
        icon="mdi:calculator-variant-outline",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: round(
            data.lifetime.simulated_system_value_pence / 100,
            2,
        ),
    ),
    KEMSSensorEntityDescription(
        key="lifetime_total_energy_cost",
        name="Lifetime net energy cost",
        icon="mdi:home-currency-gbp",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="GBP",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=_lifetime_total_cost_gbp,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_grid_independence",
        name="Lifetime grid independence",
        icon="mdi:home-percent-outline",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        value_fn=_lifetime_grid_independence,
    ),
    KEMSSensorEntityDescription(
        key="lifetime_battery_cycles",
        name="Estimated lifetime battery cycles",
        icon="mdi:battery-sync",
        native_unit_of_measurement="cycles",
        suggested_display_precision=2,
        value_fn=_estimated_battery_cycles,
    ),
    KEMSSensorEntityDescription(
        key="operating_mode",
        name="Operating mode",
        icon="mdi:tune-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control.operating_mode,
    ),
    KEMSSensorEntityDescription(
        key="virtual_control_scenario",
        name="Virtual control scenario",
        icon="mdi:test-tube",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control.virtual_scenario,
    ),
    KEMSSensorEntityDescription(
        key="control_operating_reason",
        name="Control operating reason",
        icon="mdi:information-outline",
        value_fn=lambda data: data.control.operating_reason,
    ),
    KEMSSensorEntityDescription(
        key="desired_inverter_work_mode",
        name="Desired inverter work mode",
        icon="mdi:swap-horizontal",
        value_fn=lambda data: data.control.desired_work_mode,
    ),
    KEMSSensorEntityDescription(
        key="desired_battery_charge_power",
        name="Desired battery charge power",
        icon="mdi:battery-arrow-up",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.control.desired_charge_power_kw,
    ),
    KEMSSensorEntityDescription(
        key="desired_battery_to_home_power",
        name="Desired battery to home power",
        icon="mdi:home-battery",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.control.desired_battery_to_home_power_kw,
    ),
    KEMSSensorEntityDescription(
        key="desired_battery_export_power",
        name="Desired battery export power",
        icon="mdi:transmission-tower-export",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.control.desired_battery_export_power_kw,
    ),
    KEMSSensorEntityDescription(
        key="desired_total_battery_discharge_power",
        name="Desired total battery discharge power",
        icon="mdi:battery-arrow-down",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.control.desired_total_discharge_power_kw,
    ),
    KEMSSensorEntityDescription(
        key="desired_minimum_soc",
        name="Desired minimum SOC",
        icon="mdi:battery-lock",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda data: data.control.desired_min_soc_percent,
    ),
    KEMSSensorEntityDescription(
        key="whole_house_eps_load",
        name="Whole-house EPS load",
        icon="mdi:home-lightning-bolt",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.control.whole_house_eps_load_kw,
    ),
    KEMSSensorEntityDescription(
        key="eps_headroom",
        name="EPS headroom",
        icon="mdi:gauge",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.control.eps_headroom_kw,
    ),
    KEMSSensorEntityDescription(
        key="eps_utilisation",
        name="EPS utilisation",
        icon="mdi:speedometer",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda data: data.control.eps_utilisation_percent,
    ),
    KEMSSensorEntityDescription(
        key="island_solar_to_house_power",
        name="Island solar to house power",
        icon="mdi:solar-power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.control.solar_to_house_kw,
    ),
    KEMSSensorEntityDescription(
        key="island_solar_to_battery_power",
        name="Island solar to battery power",
        icon="mdi:battery-charging",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.control.solar_to_battery_kw,
    ),
    KEMSSensorEntityDescription(
        key="island_battery_to_house_power",
        name="Island battery to house power",
        icon="mdi:home-battery-outline",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=2,
        value_fn=lambda data: data.control.battery_to_house_kw,
    ),
    KEMSSensorEntityDescription(
        key="estimated_outage_runtime",
        name="Estimated outage runtime",
        icon="mdi:timer-sand",
        native_unit_of_measurement="h",
        suggested_display_precision=1,
        value_fn=lambda data: data.control.estimated_outage_runtime_hours,
    ),
    KEMSSensorEntityDescription(
        key="control_data_age",
        name="Control data age",
        icon="mdi:timer-alert-outline",
        native_unit_of_measurement="s",
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control.data_age_seconds,
    ),
    KEMSSensorEntityDescription(
        key="control_blocked_reason",
        name="Control blocked reason",
        icon="mdi:shield-lock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control.blocked_reason,
    ),
    KEMSSensorEntityDescription(
        key="control_next_action",
        name="Control next action",
        icon="mdi:step-forward",
        value_fn=lambda data: data.control.next_action,
    ),
    KEMSSensorEntityDescription(
        key="control_preflight",
        name="Control preflight",
        icon="mdi:clipboard-check-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.control.preflight_status,
        attributes_fn=lambda data: {
            "passed": data.control.preflight_passed,
            "total": data.control.preflight_total,
        },
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
    entities = [
        KEMSSensor(coordinator, description)
        for description in SENSORS
        if _source_is_configured(description, mappings)
    ]
    entities.append(KEMSSourceValidationSensor(coordinator))
    async_add_entities(entities)


class KEMSSourceValidationSensor(KEMSEntity, SensorEntity):
    """Expose rejected or circular source mappings."""

    _attr_name = "Source validation"
    _attr_icon = "mdi:source-branch-check"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        """Initialise source validation diagnostics."""
        super().__init__(coordinator, "source_validation")

    @property
    def native_value(self) -> str:
        """Return a compact validation result."""
        rejected = self.coordinator.source_validation.rejected
        if not rejected:
            return "OK"
        return f"Rejected {len(rejected)} unsafe mapping(s)"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return accepted and rejected mapping details."""
        validation = self.coordinator.source_validation
        return {
            "valid": validation.valid,
            "summary": validation.summary(),
            "accepted": dict(sorted(validation.accepted.items())),
            "rejected": dict(sorted(validation.rejected.items())),
        }


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
