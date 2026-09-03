"""Absolute battery safety floor for Full KEMS Agile routing.

The optimiser reserve and the physical battery safety floor are deliberately
separate concepts. Full KEMS Agile normally plans toward at least 15% SOC, but
real house demand may legitimately carry the battery below that planning target
before cheap charging begins. Normal battery discharge is allowed to continue
until the absolute 10% safety floor is reached.

At or below 10%, this layer latches a discharge stop: house discharge, deliberate
export, deadline discharge and Power Down battery discharge are all blocked.
The latch remains active through the recovery band and releases only once SOC is
at least 12%. Confirmed cheap/Happy Hour charging keeps its higher-priority charge
ownership while the latch is active so the battery can recover.

This remains simulation/shadow only. Real hardware writes stay blocked.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime
from typing import Any

from .agile_rolling_planning import rolling_runtime as rolling
from .kems_core import SimulationConfig
from .tariff import TariffSettings

PLANNING_TARGET_SOC_PERCENT = 15.0
HARD_SAFETY_FLOOR_SOC_PERCENT = 10.0
HARD_SAFETY_RECOVERY_SOC_PERCENT = 12.0
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


def _planning_config(config: SimulationConfig) -> SimulationConfig:
    """Return an Agile config whose optimiser target cannot fall below 15%."""
    target = max(float(config.battery_reserve_percent), PLANNING_TARGET_SOC_PERCENT)
    if abs(target - float(config.battery_reserve_percent)) <= _EPSILON:
        return config
    return replace(config, battery_reserve_percent=target)


def _hard_safety_floor_latched(self: Any, soc: float | None) -> bool:
    """Update and return the 10% stop / 12% recovery hysteresis latch."""
    latched = bool(getattr(self, "_kems_hard_safety_floor_latched", False))
    if soc is None:
        return latched

    if latched:
        if soc >= HARD_SAFETY_RECOVERY_SOC_PERCENT - _EPSILON:
            latched = False
    elif soc <= HARD_SAFETY_FLOOR_SOC_PERCENT + _EPSILON:
        latched = True

    self._kems_hard_safety_floor_latched = latched
    return latched


def _apply_hard_safety_floor(
    plan: dict[str, Any],
    *,
    soc: float | None,
    latched: bool,
) -> dict[str, Any]:
    """Annotate the plan and stop all normal battery discharge while latched."""
    mode = str(plan.get("dispatch_mode") or "price_optimised")
    target = _number(plan.get("target_soc_percent"))
    if target is None:
        target = PLANNING_TARGET_SOC_PERCENT
    target = max(target, PLANNING_TARGET_SOC_PERCENT)

    plan.update(
        {
            "target_soc_percent": round(target, 3),
            "planning_target_soc_percent": round(target, 3),
            "planning_target_reached": soc is not None and soc <= target + _EPSILON,
            "hard_safety_floor_soc_percent": HARD_SAFETY_FLOOR_SOC_PERCENT,
            "hard_safety_recovery_soc_percent": HARD_SAFETY_RECOVERY_SOC_PERCENT,
            "hard_safety_floor_active": latched,
            "hard_reserve_soc_percent": HARD_SAFETY_FLOOR_SOC_PERCENT,
            "hard_reserve_floor_active": latched,
            "hard_reserve_policy": (
                "15% optimiser target; absolute discharge stop at 10%; remain "
                "latched until 12% recovery"
            ),
            "hardware_writes": "blocked",
        }
    )

    # Charging ownership is allowed to recover the battery. The safety latch is
    # retained in diagnostics and will clear only once a later scan sees >=12%.
    if mode in {"cheap_charge", "happy_hour_charge"}:
        plan["hard_safety_charge_recovery_active"] = latched
        return plan

    if not latched:
        plan["hard_safety_charge_recovery_active"] = False
        return plan

    plan.update(
        {
            "hard_safety_charge_recovery_active": False,
            "hard_safety_superseded_dispatch_mode": mode,
            "dispatch_mode": "hard_safety_floor",
            "dispatch_action": (
                "10% absolute battery safety floor — battery discharge stopped; "
                "grid may supply residual house demand until SOC recovers to 12%"
            ),
            "current_house_battery_kw": 0.0,
            "current_battery_export_target_kw": 0.0,
            "current_battery_discharge_target_kw": 0.0,
            "planned_battery_export_kwh": 0.0,
            "selected_slots": [],
            "next_export_slot": None,
        }
    )
    return plan


def _rolling_plan_with_hard_safety_floor(
    self: Any,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Run the canonical Agile plan with separate optimiser and safety reserves."""
    effective_config = _planning_config(config)
    plan = _original_rolling_plan(
        self,
        state,
        now=now,
        config=effective_config,
        tariff=tariff,
    )
    if not isinstance(plan, dict) or not plan.get("available"):
        return plan

    soc = _number(plan.get("simulated_soc_percent"))
    latched = _hard_safety_floor_latched(self, soc)
    return _apply_hard_safety_floor(plan, soc=soc, latched=latched)


def install_agile_safety_floor() -> None:
    """Install the final absolute battery safety owner around Agile planning."""
    rolling_plan = rolling._rolling_plan
    if getattr(rolling_plan, "_kems_agile_safety_floor", False):
        return

    global _original_rolling_plan
    _original_rolling_plan = rolling_plan
    _rolling_plan_with_hard_safety_floor._kems_agile_safety_floor = True
    rolling._rolling_plan = _rolling_plan_with_hard_safety_floor
