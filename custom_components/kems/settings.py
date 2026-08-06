"""KEMS runtime settings derived from config-entry options."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from .const import (
    CONF_ADDITIONAL_COSTS,
    CONF_ANNUAL_MAINTENANCE,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_DEGRADATION,
    CONF_BATTERY_EXPORT_ENABLED,
    CONF_BATTERY_INITIAL,
    CONF_BATTERY_POWER_POSITIVE_IS_DISCHARGE,
    CONF_BATTERY_RESERVE,
    CONF_CHARGE_EFFICIENCY,
    CONF_COMMISSIONING_DATE,
    CONF_CONTROL_ENABLED,
    CONF_DISCHARGE_EFFICIENCY,
    CONF_DISCOUNT_RATE,
    CONF_ELECTRICITY_INFLATION,
    CONF_EMERGENCY_STOP,
    CONF_EPS_CRITICAL_PERCENT,
    CONF_EPS_LIMIT,
    CONF_EPS_WARNING_PERCENT,
    CONF_EXPORT_LIMIT,
    CONF_EXPORT_RATE,
    CONF_GAS_KWH_PER_M3,
    CONF_GRANTS_REBATES,
    CONF_GRID_STABILITY_SECONDS,
    CONF_HISTORY_DAYS,
    CONF_INVERTER_LIMIT,
    CONF_ISLAND_RESERVE_PERCENT,
    CONF_MANUAL_SYSTEM_COSTS,
    CONF_MAX_CHARGE,
    CONF_MAX_DISCHARGE,
    CONF_OPERATING_MODE,
    CONF_PROPOSAL_SOLAR_ENABLED,
    CONF_PROPOSAL_SOLAR_FACTOR,
    CONF_ROI_FORECAST_YEARS,
    CONF_SAVING_SESSION_ENABLED,
    CONF_SCAN_INTERVAL,
    CONF_SIMULATION_STRATEGY,
    CONF_SITE_IMPORT_LIMIT,
    CONF_STALE_DATA_SECONDS,
    CONF_SYSTEM_COMMISSIONED,
    CONF_SYSTEM_COST,
    CONF_VIRTUAL_SCENARIO,
    DEFAULT_OPTIONS,
)
from .kems_core import ControlConfig, ROIConfig, SimulationConfig


@dataclass(frozen=True, slots=True)
class KEMSSettings:
    """Validated operational settings."""

    scan_interval_seconds: int
    history_days: int
    gas_kwh_per_m3: float
    simulation: SimulationConfig
    roi: ROIConfig
    control: ControlConfig

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> KEMSSettings:
        """Build settings using defaults for omitted options."""
        values = {**DEFAULT_OPTIONS, **dict(options)}
        commissioning_date = _parse_date(values.get(CONF_COMMISSIONING_DATE))
        return cls(
            scan_interval_seconds=max(int(values[CONF_SCAN_INTERVAL]), 30),
            history_days=max(int(values[CONF_HISTORY_DAYS]), 1),
            gas_kwh_per_m3=max(float(values[CONF_GAS_KWH_PER_M3]), 0.1),
            simulation=SimulationConfig(
                battery_capacity_kwh=float(values[CONF_BATTERY_CAPACITY]),
                battery_reserve_percent=float(values[CONF_BATTERY_RESERVE]),
                battery_initial_percent=float(values[CONF_BATTERY_INITIAL]),
                max_charge_kw=min(
                    float(values[CONF_MAX_CHARGE]),
                    max(float(values[CONF_INVERTER_LIMIT]), 0.1),
                ),
                max_discharge_kw=min(
                    float(values[CONF_MAX_DISCHARGE]),
                    max(float(values[CONF_INVERTER_LIMIT]), 0.1),
                ),
                charge_efficiency=float(values[CONF_CHARGE_EFFICIENCY]),
                discharge_efficiency=float(values[CONF_DISCHARGE_EFFICIENCY]),
                export_rate_pence=float(values[CONF_EXPORT_RATE]),
                inverter_limit_kw=max(
                    float(values[CONF_INVERTER_LIMIT]),
                    0.1,
                ),
                export_limit_kw=min(
                    float(values[CONF_EXPORT_LIMIT]),
                    max(float(values[CONF_INVERTER_LIMIT]), 0.1),
                ),
                eps_output_limit_kw=max(float(values[CONF_EPS_LIMIT]), 0.1),
                site_import_limit_kw=(
                    max(float(values[CONF_SITE_IMPORT_LIMIT]), 0.0) or None
                ),
                battery_export_enabled=bool(values[CONF_BATTERY_EXPORT_ENABLED]),
                proposal_solar_enabled=bool(values[CONF_PROPOSAL_SOLAR_ENABLED]),
                proposal_solar_factor=float(values[CONF_PROPOSAL_SOLAR_FACTOR]),
                battery_power_positive_is_discharge=bool(
                    values[CONF_BATTERY_POWER_POSITIVE_IS_DISCHARGE]
                ),
                saving_session_enabled=bool(values[CONF_SAVING_SESSION_ENABLED]),
                strategy=(
                    "self_use"
                    if str(values[CONF_SIMULATION_STRATEGY]) == "self_use"
                    else "paced_export"
                ),
            ),
            roi=ROIConfig(
                system_cost_gbp=max(float(values[CONF_SYSTEM_COST]), 0.0),
                additional_costs_gbp=max(float(values[CONF_ADDITIONAL_COSTS]), 0.0),
                grants_rebates_gbp=max(float(values[CONF_GRANTS_REBATES]), 0.0),
                commissioning_date=commissioning_date,
                annual_maintenance_gbp=max(
                    float(values[CONF_ANNUAL_MAINTENANCE]),
                    0.0,
                ),
                manual_system_costs_gbp=max(
                    float(values[CONF_MANUAL_SYSTEM_COSTS]),
                    0.0,
                ),
                electricity_inflation_percent=float(values[CONF_ELECTRICITY_INFLATION]),
                battery_degradation_percent=max(
                    float(values[CONF_BATTERY_DEGRADATION]),
                    0.0,
                ),
                discount_rate_percent=max(float(values[CONF_DISCOUNT_RATE]), 0.0),
                forecast_years=max(int(values[CONF_ROI_FORECAST_YEARS]), 1),
            ),
            control=ControlConfig(
                operating_mode=str(values[CONF_OPERATING_MODE]),
                virtual_scenario=str(values[CONF_VIRTUAL_SCENARIO]),
                control_enabled=bool(values[CONF_CONTROL_ENABLED]),
                commissioned=bool(values[CONF_SYSTEM_COMMISSIONED]),
                emergency_stop=bool(values[CONF_EMERGENCY_STOP]),
                stale_data_seconds=max(int(values[CONF_STALE_DATA_SECONDS]), 30),
                grid_stability_seconds=max(
                    int(values[CONF_GRID_STABILITY_SECONDS]), 30
                ),
                eps_limit_kw=max(float(values[CONF_EPS_LIMIT]), 0.1),
                eps_warning_percent=float(values[CONF_EPS_WARNING_PERCENT]),
                eps_critical_percent=float(values[CONF_EPS_CRITICAL_PERCENT]),
                island_reserve_percent=float(values[CONF_ISLAND_RESERVE_PERCENT]),
                normal_reserve_percent=float(values[CONF_BATTERY_RESERVE]),
                battery_capacity_kwh=float(values[CONF_BATTERY_CAPACITY]),
                discharge_efficiency=float(values[CONF_DISCHARGE_EFFICIENCY]),
                max_charge_kw=min(
                    float(values[CONF_MAX_CHARGE]),
                    max(float(values[CONF_INVERTER_LIMIT]), 0.1),
                ),
                max_discharge_kw=min(
                    float(values[CONF_MAX_DISCHARGE]),
                    max(float(values[CONF_INVERTER_LIMIT]), 0.1),
                ),
                export_limit_kw=min(
                    float(values[CONF_EXPORT_LIMIT]),
                    max(float(values[CONF_INVERTER_LIMIT]), 0.1),
                ),
                inverter_limit_kw=max(float(values[CONF_INVERTER_LIMIT]), 0.1),
                site_import_limit_kw=(
                    max(float(values[CONF_SITE_IMPORT_LIMIT]), 0.0) or None
                ),
            ),
        )


def _parse_date(value: Any) -> date | None:
    """Parse an optional ISO date from Home Assistant options."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None
