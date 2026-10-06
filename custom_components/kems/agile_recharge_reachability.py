"""Protect enough pre-cheap SOC to complete the guaranteed overnight recharge.

Full KEMS may deliberately export battery energy before the normal overnight
cheap window. The economic/export target must not be lower than the SOC required
for the configured charger to reach 100% by the end of that guaranteed cheap
window.

This layer changes only Agile planning allocation. It does not grant hardware
write authority. The physical 10% MinSOC safety floor and 12% recovery latch
remain independent and unchanged.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, time, timedelta
from typing import Any

from .agile_rolling_planning import rolling_runtime as rolling
from .kems_core import SimulationConfig
from .tariff import TariffSettings

FULL_CHARGE_TARGET_PERCENT = 100.0
MINIMUM_AGILE_PLANNING_TARGET_PERCENT = 15.0
_EPSILON = 1e-6


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _cheap_window_hours(start: time, end: time) -> float:
    """Return the guaranteed daily cheap-window duration in hours."""
    anchor = datetime(2026, 1, 1)
    start_dt = datetime.combine(anchor.date(), start)
    end_dt = datetime.combine(anchor.date(), end)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return max((end_dt - start_dt).total_seconds() / 3600.0, 0.0)


def _required_precheap_soc_percent(
    config: SimulationConfig,
    tariff: TariffSettings,
    *,
    target_soc_percent: float = FULL_CHARGE_TARGET_PERCENT,
) -> dict[str, Any]:
    """Return the minimum SOC needed at cheap start to hit the charge target."""
    capacity = max(_number(config.battery_capacity_kwh) or 0.0, 0.0)
    charge_kw = max(_number(config.max_charge_kw) or 0.0, 0.0)
    efficiency = min(max(_number(config.charge_efficiency) or 0.0, 0.0), 1.0)
    target = min(max(_number(target_soc_percent) or 0.0, 0.0), 100.0)
    hours = _cheap_window_hours(tariff.offpeak_start, tariff.offpeak_end)

    if capacity <= _EPSILON:
        return {
            "available": False,
            "reason": "battery capacity is unavailable",
            "required_precheap_soc_percent": None,
            "hardware_writes": "blocked",
        }

    maximum_input_kwh = charge_kw * hours
    maximum_stored_kwh = min(maximum_input_kwh * efficiency, capacity)
    achievable_gain_percent = maximum_stored_kwh / capacity * 100.0
    required = min(max(target - achievable_gain_percent, 0.0), target)

    return {
        "available": True,
        "target_soc_percent": round(target, 3),
        "guaranteed_cheap_window_hours": round(hours, 4),
        "max_charge_kw": round(charge_kw, 3),
        "charge_efficiency": round(efficiency, 4),
        "maximum_charge_input_kwh": round(maximum_input_kwh, 3),
        "maximum_stored_charge_kwh": round(maximum_stored_kwh, 3),
        "maximum_soc_gain_percent": round(achievable_gain_percent, 3),
        "required_precheap_soc_percent": round(required, 3),
        "basis": (
            "target SOC minus guaranteed cheap-window stored-charge capability"
        ),
        "hardware_writes": "blocked",
    }


def _rolling_plan_with_recharge_reachability(
    self: Any,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Run the existing planner with a reserve high enough to recharge fully."""
    evidence = _required_precheap_soc_percent(config, tariff)
    required = _number(evidence.get("required_precheap_soc_percent"))
    configured_target = max(
        _number(config.battery_reserve_percent) or 0.0,
        MINIMUM_AGILE_PLANNING_TARGET_PERCENT,
    )
    effective_target = max(configured_target, required or 0.0)
    effective_target = min(max(effective_target, 0.0), 100.0)

    effective_config = (
        replace(config, battery_reserve_percent=effective_target)
        if abs(effective_target - float(config.battery_reserve_percent)) > _EPSILON
        else config
    )
    plan = _original_rolling_plan(
        self,
        state,
        now=now,
        config=effective_config,
        tariff=tariff,
    )
    if not isinstance(plan, dict):
        return plan

    evidence.update(
        {
            "configured_planning_target_percent": round(configured_target, 3),
            "effective_precheap_target_soc_percent": round(effective_target, 3),
            "reserve_raised_for_full_recharge": (
                required is not None
                and effective_target > configured_target + _EPSILON
            ),
            "policy": (
                "retain enough SOC at guaranteed cheap start for the configured "
                "charger to reach 100% by cheap-window end"
            ),
        }
    )
    plan["recharge_reachability"] = evidence
    plan["recharge_reachability_floor_soc_percent"] = round(effective_target, 3)
    plan["effective_precheap_target_soc_percent"] = round(effective_target, 3)
    return plan


def install_recharge_reachability() -> None:
    """Wrap the current Agile rolling planner with the recharge floor."""
    current = rolling._rolling_plan
    if getattr(current, "_kems_recharge_reachability", False):
        return

    global _original_rolling_plan
    _original_rolling_plan = current
    _rolling_plan_with_recharge_reachability._kems_recharge_reachability = True
    rolling._rolling_plan = _rolling_plan_with_recharge_reachability
