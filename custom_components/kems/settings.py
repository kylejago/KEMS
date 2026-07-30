"""KEMS runtime settings derived from config-entry options."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_INITIAL,
    CONF_BATTERY_RESERVE,
    CONF_CHARGE_EFFICIENCY,
    CONF_DISCHARGE_EFFICIENCY,
    CONF_EXPORT_RATE,
    CONF_HISTORY_DAYS,
    CONF_MAX_CHARGE,
    CONF_MAX_DISCHARGE,
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
    simulation: SimulationConfig

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> KEMSSettings:
        """Build settings using defaults for omitted options."""
        values = {**DEFAULT_OPTIONS, **dict(options)}
        return cls(
            scan_interval_seconds=max(int(values[CONF_SCAN_INTERVAL]), 30),
            history_days=max(int(values[CONF_HISTORY_DAYS]), 1),
            simulation=SimulationConfig(
                battery_capacity_kwh=float(values[CONF_BATTERY_CAPACITY]),
                battery_reserve_percent=float(values[CONF_BATTERY_RESERVE]),
                battery_initial_percent=float(values[CONF_BATTERY_INITIAL]),
                max_charge_kw=float(values[CONF_MAX_CHARGE]),
                max_discharge_kw=float(values[CONF_MAX_DISCHARGE]),
                charge_efficiency=float(values[CONF_CHARGE_EFFICIENCY]),
                discharge_efficiency=float(values[CONF_DISCHARGE_EFFICIENCY]),
                export_rate_pence=float(values[CONF_EXPORT_RATE]),
                strategy=str(values[CONF_SIMULATION_STRATEGY]),
            ),
        )
