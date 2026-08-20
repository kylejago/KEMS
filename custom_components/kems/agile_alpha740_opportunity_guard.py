"""Alpha7.40 proactive Agile opportunity guard.

The existing rolling planner ranks the remaining Agile slots by price and the
Alpha7.34 deadline guard prevents KEMS from missing the 10% pre-cheap target.
Alpha7.40 adds one more economic safety layer: if waiting would force part of the
remaining exportable energy into a cheaper slot, KEMS starts in the current
higher-value slot before the hard latest-safe-start cliff.

This is deliberately conservative. It never increases total exportable energy,
never weakens the 10% SOC floor, and never exceeds the existing solar-aware
shared-inverter/export limits. It only moves already-planned battery export
forward when doing so improves the expected price result and preserves a small
forecast/capacity uncertainty margin.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_alpha717_dispatch as alpha717
from . import agile_rolling_replan as rolling
from .kems_core import SimulationConfig
from .tariff import TariffSettings

_EPSILON = 1e-6
PRICE_ADVANTAGE_PENCE = 0.15
UNCERTAINTY_MARGIN_FRACTION = 0.08


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dt(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _current_slot(state: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    now_utc = now.astimezone(UTC)
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        start = _dt(slot.get("valid_from"))
        end = _dt(slot.get("valid_to"))
        if start is not None and end is not None and start <= now_utc < end:
            return slot
    return None


def _remaining_hours(slot: dict[str, Any], now: datetime) -> float:
    end = _dt(slot.get("valid_to"))
    if end is None:
        return 0.0
    return max((end - now.astimezone(UTC)).total_seconds() / 3600.0, 0.0)


def _economic_guard(
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    effective_kw: float,
) -> dict[str, Any]:
    """Return proactive current-slot export evidence and minimum energy."""
    current = _current_slot(state, now)
    if current is None or effective_kw <= _EPSILON:
        return {"active": False, "reason": "no current Agile slot", "minimum_current_export_kwh": 0.0}

    current_rate = _number(current.get("rate_pence")) or 0.0
    remaining_hours = _remaining_hours(current, now)
    current_capacity = max(effective_kw * remaining_hours, 0.0)
    if current_capacity <= _EPSILON or current_rate <= 0:
        return {"active": False, "reason": "current slot has no useful export capacity", "minimum_current_export_kwh": 0.0}

    exportable = max(_number(plan.get("exportable_battery_energy_kwh")) or 0.0, 0.0)
    planned = max(_number(plan.get("planned_battery_export_kwh")) or 0.0, 0.0)
    if exportable <= _EPSILON or planned <= _EPSILON:
        return {"active": False, "reason": "no exportable battery energy", "minimum_current_export_kwh": 0.0}

    future: list[tuple[float, float]] = []
    now_utc = now.astimezone(UTC)
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict) or slot is current:
            continue
        start = _dt(slot.get("valid_from"))
        end = _dt(slot.get("valid_to"))
        if start is None or end is None or end <= now_utc:
            continue
        rate = _number(slot.get("rate_pence")) or 0.0
        if rate <= 0:
            continue
        hours = max((end - max(start, now_utc)).total_seconds() / 3600.0, 0.0)
        if hours > _EPSILON:
            future.append((rate, effective_kw * hours))

    if not future:
        return {"active": False, "reason": "no positive future export slots", "minimum_current_export_kwh": 0.0}

    future.sort(key=lambda item: item[0], reverse=True)
    remaining_need = min(planned, exportable)
    future_capacity = sum(capacity for _, capacity in future)
    uncertainty_margin = min(
        remaining_need * UNCERTAINTY_MARGIN_FRACTION,
        effective_kw * 0.25,
    )
    protected_need = min(remaining_need + uncertainty_margin, exportable)

    cumulative = 0.0
    marginal_future_rate = future[-1][0]
    for rate, capacity in future:
        cumulative += capacity
        marginal_future_rate = rate
        if cumulative + _EPSILON >= protected_need:
            break

    shortage_without_now = max(protected_need - future_capacity, 0.0)
    price_advantage = current_rate - marginal_future_rate
    proactive = min(max(shortage_without_now, 0.0), current_capacity, remaining_need)

    # If the current slot is materially better than the marginal future slot,
    # reserve a small slice now even when raw future capacity is just sufficient.
    # This avoids riding the mathematical edge and later being forced into a
    # weaker price after forecast/headroom movement.
    if proactive <= _EPSILON and price_advantage >= PRICE_ADVANTAGE_PENCE:
        proactive = min(
            current_capacity,
            remaining_need,
            max(uncertainty_margin, min(effective_kw * 0.10, remaining_need)),
        )

    return {
        "active": proactive > _EPSILON,
        "reason": (
            "current higher-value slot protects economic outcome before latest-safe cliff"
            if proactive > _EPSILON
            else "future capacity and prices do not justify early export"
        ),
        "current_rate_pence": round(current_rate, 5),
        "marginal_future_rate_pence": round(marginal_future_rate, 5),
        "price_advantage_pence": round(price_advantage, 5),
        "future_capacity_kwh": round(future_capacity, 3),
        "uncertainty_margin_kwh": round(uncertainty_margin, 3),
        "minimum_current_export_kwh": round(proactive, 3),
        "policy": "economic opportunity + forecast-capacity uncertainty guard",
    }


def install_alpha740_opportunity_guard_patch() -> None:
    """Install proactive economic dispatch after the proven Alpha7.34 guard."""
    dispatch = alpha717._dispatch_targets
    if not getattr(dispatch, "_kems_alpha740_opportunity_guard", False):
        original_dispatch = dispatch

        def dispatch_with_alpha740(
            self,
            state,
            plan,
            *,
            now,
            config: SimulationConfig,
            tariff: TariffSettings,
        ):
            targets = original_dispatch(
                self,
                state,
                plan,
                now=now,
                config=config,
                tariff=tariff,
            )
            if not isinstance(targets, dict) or not targets.get("available"):
                return targets
            mode = str(targets.get("mode") or "")
            if mode in {"maximum_discharge", "target_reached"}:
                return targets

            effective_kw = max(_number(targets.get("effective_discharge_kw")) or 0.0, 0.0)
            guard = _economic_guard(state, plan, now=now, effective_kw=effective_kw)
            targets["economic_opportunity_guard"] = guard
            if not guard.get("active"):
                return targets

            current = _current_slot(state, now)
            hours = _remaining_hours(current, now) if current is not None else 0.0
            minimum_kwh = max(_number(guard.get("minimum_current_export_kwh")) or 0.0, 0.0)
            minimum_kw = minimum_kwh / hours if hours > _EPSILON else 0.0
            house_kw = max(_number(targets.get("house_battery_kw")) or 0.0, 0.0)
            existing_export = max(_number(targets.get("battery_export_target_kw")) or 0.0, 0.0)
            export_kw = min(
                max(existing_export, minimum_kw),
                max(config.export_limit_kw, 0.0),
                max(config.inverter_limit_kw - house_kw, 0.0),
                max(config.max_discharge_kw - house_kw, 0.0),
            )
            total_kw = min(house_kw + export_kw, effective_kw)
            export_kw = max(total_kw - house_kw, 0.0)
            targets.update(
                {
                    "mode": "economic_preemptive_export" if mode == "price_optimised" else mode,
                    "battery_export_target_kw": round(export_kw, 3),
                    "battery_discharge_target_kw": round(total_kw, 3),
                    "planned_price_export_kw": round(
                        max(_number(targets.get("planned_price_export_kw")) or 0.0, export_kw),
                        3,
                    ),
                    "action": (
                        "proactive Agile export — use the stronger current price before "
                        "forecast/headroom uncertainty can force energy into a cheaper slot"
                    ),
                }
            )
            return targets

        dispatch_with_alpha740._kems_alpha740_opportunity_guard = True
        alpha717._dispatch_targets = dispatch_with_alpha740

    plan_function = rolling._rolling_plan
    if not getattr(plan_function, "_kems_alpha740_opportunity_guard", False):
        original_plan = plan_function

        def rolling_plan_with_alpha740(
            self,
            state,
            *,
            now,
            config: SimulationConfig,
            tariff: TariffSettings,
        ):
            plan = original_plan(self, state, now=now, config=config, tariff=tariff)
            if not isinstance(plan, dict) or not plan.get("available"):
                return plan
            effective_kw = max(_number(plan.get("effective_discharge_kw")) or 0.0, 0.0)
            guard = _economic_guard(state, plan, now=now, effective_kw=effective_kw)
            plan["economic_opportunity_guard"] = guard
            plan["economic_guard_active"] = bool(guard.get("active"))
            plan["economic_guard_price_advantage_pence"] = guard.get("price_advantage_pence")
            plan["economic_guard_minimum_current_export_kwh"] = guard.get("minimum_current_export_kwh")
            return plan

        rolling_plan_with_alpha740._kems_alpha740_opportunity_guard = True
        rolling._rolling_plan = rolling_plan_with_alpha740
