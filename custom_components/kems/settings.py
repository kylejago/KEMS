"""KEMS runtime settings derived from config-entry options."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_EXPORT_ENABLED,
    CONF_BATTERY_INITIAL,
    CONF_BATTERY_RESERVE,
    CONF_CHARGE_EFFICIENCY,
    CONF_DISCHARGE_EFFICIENCY,
    CONF_EXPORT_LIMIT,
    CONF_EXPORT_RATE,
    CONF_GAS_KWH_PER_M3,
    CONF_HISTORY_DAYS,
    CONF_MAX_CHARGE,
    CONF_MAX_DISCHARGE,
    CONF_PROPOSAL_SOLAR_ENABLED,
    CONF_PROPOSAL_SOLAR_FACTOR,
    CONF_SCAN_INTERVAL,
    CONF_SIMULATION_STRATEGY,
    DEFAULT_OPTIONS,
)
from .kems_core import SimulationConfig


@dataclass(frozen=True, slots=True)
class KEMSSettings:
    """Validated operational settings."""

    scan_interval_seconds: int
    history_days: int
    gas_kwh_per_m3: float
    simulation: SimulationConfig

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> KEMSSettings:
        """Build settings using defaults for omitted options."""
        values = {**DEFAULT_OPTIONS, **dict(options)}
        return cls(
            scan_interval_seconds=max(int(values[CONF_SCAN_INTERVAL]), 30),
            history_days=max(int(values[CONF_HISTORY_DAYS]), 1),
            gas_kwh_per_m3=max(float(values[CONF_GAS_KWH_PER_M3]), 0.1),
            simulation=SimulationConfig(
                battery_capacity_kwh=float(values[CONF_BATTERY_CAPACITY]),
                battery_reserve_percent=float(values[CONF_BATTERY_RESERVE]),
                battery_initial_percent=float(values[CONF_BATTERY_INITIAL]),
                max_charge_kw=float(values[CONF_MAX_CHARGE]),
                max_discharge_kw=float(values[CONF_MAX_DISCHARGE]),
                charge_efficiency=float(values[CONF_CHARGE_EFFICIENCY]),
                discharge_efficiency=float(values[CONF_DISCHARGE_EFFICIENCY]),
                export_rate_pence=float(values[CONF_EXPORT_RATE]),
                export_limit_kw=float(values[CONF_EXPORT_LIMIT]),
                battery_export_enabled=bool(values[CONF_BATTERY_EXPORT_ENABLED]),
                proposal_solar_enabled=bool(values[CONF_PROPOSAL_SOLAR_ENABLED]),
                proposal_solar_factor=float(values[CONF_PROPOSAL_SOLAR_FACTOR]),
                strategy=str(values[CONF_SIMULATION_STRATEGY]),
            ),
        )
