"""Keep the 15% Agile planning target separate from the 10% house floor.

The rolling optimiser already treats 15% as the point where deliberate battery
export must stop, while the independent safety owner permits ordinary house
service down to the absolute 10% floor. The customer-facing future-flow
projection historically reused the 15% planning reserve for both purposes. As
its displayed SOC was rebased against live state, that could publish avoidable
pre-cheap Grid IMPORT rows around 15% even though the real routing policy would
continue serving the home from battery.

This presentation-only layer runs the existing projection unchanged except for
its house-service reserve. The projection still uses the forecast/pre-cheap
planning target for deliberate export, but its battery-to-home precision helper
and final SOC clamp use the 10% hard floor. The existing 10% stop / 12% recovery
latch remains authoritative; when already latched, the projection does not
invent further battery-to-home discharge. No optimiser allocation, tariff,
FoxESS command or hardware-write authority changes here.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import replace
from typing import Any

from . import agile_flow_presentation as flow
from .agile_safety_floor import (
    HARD_SAFETY_FLOOR_SOC_PERCENT,
    HARD_SAFETY_RECOVERY_SOC_PERCENT,
    PLANNING_TARGET_SOC_PERCENT,
)
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    SolarForecastState,
)
from .tariff import TariffSettings

_HOUSE_FLOOR_KWH: ContextVar[float | None] = ContextVar(
    "kems_agile_projection_house_floor_kwh",
    default=None,
)
_original_future_today_projection = None
_original_close_home_precision_residual = None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _rolling_plan(state: dict[str, Any]) -> dict[str, Any]:
    value = state.get("rolling_export_plan")
    return value if isinstance(value, dict) else {}


def _current_soc_percent(state: dict[str, Any]) -> float | None:
    routing = state.get("current_routing_snapshot")
    if isinstance(routing, dict):
        soc = _number(routing.get("simulated_soc_percent"))
        if soc is not None:
            return min(max(soc, 0.0), 100.0)
    return _number(_rolling_plan(state).get("simulated_soc_percent"))


def _projection_reserve_percent(state: dict[str, Any]) -> tuple[float, bool]:
    """Return the display clamp and whether the restart-safe safety latch is active."""
    rolling = _rolling_plan(state)
    latched = bool(rolling.get("hard_safety_floor_active"))
    if not latched:
        return HARD_SAFETY_FLOOR_SOC_PERCENT, False

    # Do not manufacture stored energy when the persisted latch was entered
    # slightly below 10%. While latched the house helper is separately blocked.
    current_soc = _current_soc_percent(state)
    if current_soc is None:
        return HARD_SAFETY_FLOOR_SOC_PERCENT, True
    return min(current_soc, HARD_SAFETY_FLOOR_SOC_PERCENT), True


def _house_floor_close(
    *,
    remaining_house_kwh: float,
    battery_home_kwh: float,
    battery_energy_kwh: float,
    floor_kwh: float,
    discharge_limit_kwh: float,
    discharge_efficiency: float,
) -> float:
    """Use the hard floor for Home service while leaving export floor untouched."""
    override = _HOUSE_FLOOR_KWH.get()
    effective_floor = floor_kwh if override is None else override
    return _original_close_home_precision_residual(
        remaining_house_kwh=remaining_house_kwh,
        battery_home_kwh=battery_home_kwh,
        battery_energy_kwh=battery_energy_kwh,
        floor_kwh=effective_floor,
        discharge_limit_kwh=discharge_limit_kwh,
        discharge_efficiency=discharge_efficiency,
    )


def _future_today_projection_with_separate_reserves(
    self,
    state: dict[str, Any],
    *,
    now,
    config: SimulationConfig,
    learned: LearnedState,
    forecast: SolarForecastState,
    forecast_plan: ForecastPlanState,
    tariff: TariffSettings,
) -> dict[str, dict[str, Any]]:
    """Run the canonical flow projection with separate export and house reserves."""
    reserve_percent, latched = _projection_reserve_percent(state)
    effective_config = replace(config, battery_reserve_percent=reserve_percent)
    capacity = max(float(config.battery_capacity_kwh), 0.1)
    house_floor_kwh = capacity * HARD_SAFETY_FLOOR_SOC_PERCENT / 100.0

    # A live safety latch owns discharge until recovery. Using full capacity as
    # the helper floor suppresses projected house discharge without weakening
    # the original export/pre-cheap target calculation. Otherwise the Home may
    # bridge from 15% down toward the independent 10% hard floor.
    helper_floor_kwh = capacity if latched else house_floor_kwh
    token = _HOUSE_FLOOR_KWH.set(helper_floor_kwh)
    try:
        projected = _original_future_today_projection(
            self,
            state,
            now=now,
            config=effective_config,
            learned=learned,
            forecast=forecast,
            forecast_plan=forecast_plan,
            tariff=tariff,
        )
    finally:
        _HOUSE_FLOOR_KWH.reset(token)

    planning_target = max(
        float(config.battery_reserve_percent),
        _number(getattr(forecast_plan, "minimum_precheap_soc_percent", None)) or 0.0,
        PLANNING_TARGET_SOC_PERCENT,
    )
    for row in projected.values():
        if not isinstance(row, dict):
            continue
        row.update(
            {
                "planning_target_soc_percent": round(planning_target, 3),
                "house_import_floor_soc_percent": HARD_SAFETY_FLOOR_SOC_PERCENT,
                "hard_safety_recovery_soc_percent": HARD_SAFETY_RECOVERY_SOC_PERCENT,
                "planning_target_limits_export_only": True,
                "hard_safety_floor_latched": latched,
            }
        )
    return projected


def install_flow_reserve_policy() -> None:
    """Bind the separate 15/10/12 policy to the real future-flow projection."""
    global _original_future_today_projection, _original_close_home_precision_residual

    projection = flow._future_today_projection
    if getattr(projection, "_kems_flow_reserve_policy", False):
        return

    _original_future_today_projection = projection
    _original_close_home_precision_residual = flow._close_home_precision_residual
    _house_floor_close._kems_flow_reserve_policy = True
    _future_today_projection_with_separate_reserves._kems_flow_reserve_policy = True
    flow._close_home_precision_residual = _house_floor_close
    flow._future_today_projection = _future_today_projection_with_separate_reserves
