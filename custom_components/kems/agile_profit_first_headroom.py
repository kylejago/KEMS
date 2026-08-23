"""Profit-first forecast solar-headroom allocation for Full KEMS Agile.

Solar forecast is a timing constraint, not a second export-price floor. When a
high-confidence forecast says battery headroom must exist before incoming solar
would otherwise spill, KEMS moves only already-planned battery export into the
highest-value feasible pre-spill slots that remain above the configured overnight
replacement-cost floor. Later planned export is removed from its lowest-value
slots first so the total planned battery export is not increased.

The normal 10% reserve/deadline target, house protection, price-horizon safety,
Power Down priority and hardware-write boundary remain unchanged. Real hardware
writes remain blocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import agile_forecast_arbitrage as forecast_runtime
from . import agile_rolling_planning
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    SolarForecastState,
)
from .tariff import TariffSettings

rolling = agile_rolling_planning.rolling_runtime
_EPSILON = 1e-6


def _number(value: Any) -> float | None:
    """Use the canonical finite-number parser."""
    return forecast_runtime._number(value)


def _candidate_is_economic(rate_pence: float, floor_pence: float) -> bool:
    """Return whether one battery-export slot clears replacement cost."""
    return rate_pence + _EPSILON >= floor_pence


def _rank_candidates(
    candidates: list[tuple[float, datetime, str, float]],
) -> list[tuple[float, datetime, str, float]]:
    """Prefer the highest Agile price, then the earliest equal-price slot."""
    return sorted(candidates, key=lambda item: (-item[0], item[1]))


def _retime_for_profit_first_solar_headroom(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    allocations: dict[str, float],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
    forecast: SolarForecastState | None,
    forecast_plan: ForecastPlanState | None,
    learned: LearnedState | None,
    effective_target_soc_percent: float,
) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
    """Move planned export only as required by forecast headroom timing.

    The solar forecast determines *how much* export must occur before the first
    forecast spill. The Agile price curve determines *where* that constrained
    export goes: highest eligible pre-spill prices first, with the overnight
    replacement price as the economic floor. The spill-period export price is
    retained as evidence but is not an additional candidate threshold.
    """
    deadline = forecast_runtime.agile._next_cheap(now, tariff).astimezone(UTC)
    soc = rolling._current_agile_soc(state)
    projection = forecast_runtime._forecast_spill_projection(
        now=now,
        deadline=deadline,
        soc_percent=soc,
        config=config,
        forecast=forecast,
        forecast_plan=forecast_plan,
        learned=learned,
        effective_target_soc_percent=effective_target_soc_percent,
    )
    evidence: dict[str, Any] = {
        **projection,
        "active": False,
        "re_timed_export_kwh": 0.0,
        "expected_value_gain_pence": 0.0,
        "expected_profit_above_replacement_pence": 0.0,
        "profit_first_headroom": True,
        "selection_basis": (
            "forecast sets required pre-spill headroom; highest eligible Agile "
            "prices above overnight replacement cost are selected first"
        ),
    }
    if not projection.get("available") or projection.get("state") != "spill_expected":
        return allocations, {}, evidence

    first_spill = forecast_runtime._dt(projection.get("first_spill_at"))
    if first_spill is None or first_spill <= now.astimezone(UTC):
        evidence["reason"] = "forecast spill is already active or has passed"
        return allocations, {}, evidence

    slots = forecast_runtime._slot_map(state)
    spill_rate = forecast_runtime._spill_reference_rate(state, projection)
    floor_pence = forecast_runtime._economic_export_floor_pence(tariff)
    evidence["spill_reference_rate_pence"] = (
        round(spill_rate, 5) if spill_rate is not None else None
    )
    evidence["economic_export_floor_pence"] = round(floor_pence, 5)
    evidence["spill_price_is_candidate_threshold"] = False

    existing_early = 0.0
    for key, allocation in allocations.items():
        slot = slots.get(key) or {}
        end = forecast_runtime._dt(slot.get("valid_to"))
        if end is not None and end <= first_spill:
            existing_early += allocation

    required = max(
        (_number(projection.get("required_early_export_kwh")) or 0.0) - existing_early,
        0.0,
    )
    if required <= _EPSILON:
        evidence.update(
            {
                "state": "headroom_already_planned",
                "reason": "existing planned export already creates forecast headroom",
                "existing_pre_spill_export_kwh": round(existing_early, 3),
            }
        )
        return allocations, {}, evidence

    effective_kw = max(_number(plan.get("effective_discharge_kw")) or 0.0, 0.0)
    current_house_kw = rolling._current_house_headroom_kw(self, config)
    candidates: list[tuple[float, datetime, str, float]] = []
    now_utc = now.astimezone(UTC)
    for key, slot in slots.items():
        start = forecast_runtime._dt(slot.get("valid_from"))
        end = forecast_runtime._dt(slot.get("valid_to"))
        rate = _number(slot.get("rate_pence"))
        if start is None or end is None or rate is None:
            continue
        overlap_start = max(start, now_utc)
        overlap_end = min(end, first_spill)
        if overlap_end <= overlap_start:
            continue
        if not _candidate_is_economic(rate, floor_pence):
            continue
        available_kw = effective_kw
        if start <= now_utc < end:
            available_kw = max(available_kw - current_house_kw, 0.0)
        capacity_kwh = available_kw * (
            (overlap_end - overlap_start).total_seconds() / 3600.0
        )
        spare = max(capacity_kwh - allocations.get(key, 0.0), 0.0)
        if spare > _EPSILON:
            candidates.append((rate, start, key, spare))

    # Only re-time energy that was already due to be exported later. Removing
    # lowest-value later allocations first preserves the strongest later prices.
    donors = [
        key
        for key, allocation in allocations.items()
        if allocation > _EPSILON
        and (forecast_runtime._dt((slots.get(key) or {}).get("valid_from")) or now_utc)
        >= first_spill
    ]
    donor_available = sum(allocations[key] for key in donors)
    if not candidates or donor_available <= _EPSILON:
        evidence.update(
            {
                "state": "waiting_for_retimable_export",
                "reason": (
                    "forecast needs earlier headroom but no economically eligible "
                    "pre-spill capacity can replace later planned export"
                ),
                "existing_pre_spill_export_kwh": round(existing_early, 3),
            }
        )
        return allocations, {}, evidence

    remaining = min(required, donor_available)
    additions: dict[str, float] = {}
    profit_above_floor = 0.0
    for rate, _, key, spare in _rank_candidates(candidates):
        if remaining <= _EPSILON:
            break
        addition = min(spare, remaining)
        allocations[key] = allocations.get(key, 0.0) + addition
        additions[key] = additions.get(key, 0.0) + addition
        profit_above_floor += addition * max(rate - floor_pence, 0.0)
        remaining -= addition

    shifted = sum(additions.values())
    to_remove = shifted
    removed: list[dict[str, Any]] = []
    for key in sorted(
        donors,
        key=lambda value: (
            _number((slots.get(value) or {}).get("rate_pence")) or 0.0,
            value,
        ),
    ):
        if to_remove <= _EPSILON:
            break
        reduction = min(allocations[key], to_remove)
        allocations[key] -= reduction
        to_remove -= reduction
        removed.append(
            {
                "valid_from": key,
                "rate_pence": _number((slots.get(key) or {}).get("rate_pence")),
                "removed_export_kwh": round(reduction, 3),
            }
        )

    shifted -= max(to_remove, 0.0)
    if shifted <= _EPSILON:
        return allocations, {}, evidence

    # Keep the historical field for dashboards, but make its basis explicit.
    evidence.update(
        {
            "active": True,
            "state": "headroom_retimed_profit_first",
            "reason": (
                "forecast requires battery headroom before incoming solar; "
                "constrained export allocated to highest pre-spill Agile prices"
            ),
            "existing_pre_spill_export_kwh": round(existing_early, 3),
            "re_timed_export_kwh": round(shifted, 3),
            "expected_value_gain_pence": round(profit_above_floor, 2),
            "expected_value_gain_basis": "export value above overnight replacement cost",
            "expected_profit_above_replacement_pence": round(profit_above_floor, 2),
            "candidate_slots": [
                {
                    "valid_from": key,
                    "rate_pence": _number((slots.get(key) or {}).get("rate_pence")),
                    "added_export_kwh": round(value, 3),
                }
                for key, value in sorted(additions.items())
            ],
            "later_slots_reduced": removed,
            "total_planned_battery_export_increased": False,
        }
    )
    return allocations, additions, evidence


def install_profit_first_headroom() -> None:
    """Install profit-first solar-headroom allocation exactly once."""
    current = forecast_runtime._retime_for_solar_headroom
    if getattr(current, "_kems_profit_first_headroom", False):
        return
    _retime_for_profit_first_solar_headroom._kems_profit_first_headroom = True
    forecast_runtime._retime_for_solar_headroom = _retime_for_profit_first_solar_headroom
