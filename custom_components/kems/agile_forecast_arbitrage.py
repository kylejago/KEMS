"""Forecast-protected and solar-headroom planning for Full KEMS Agile.

This is a post-Alpha8 behavioural layer. It deliberately leaves the frozen
Alpha7.52-compatible runtimes byte-identical and adjusts their live plan through
canonical module objects instead.

The policy has three bounded effects:

* never deliberately export below the configured overnight replacement rate;
* never plan below the forecast minimum SOC required at the cheap-window start;
* when high-confidence solar is likely to overflow a full battery, move already
  planned battery export into an earlier better-priced slot so later solar has
  room to charge.

Solar headroom only re-times existing planned battery export. It never increases
the day's planned battery export from forecast solar and never weakens protected
house/reserve energy. Real hardware writes remain blocked.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from . import agile_deadline_guard
from . import agile_rolling_planning
from . import agile_settlement_dispatch
from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from .agile_deadline_dispatch import _effective_deadline_kw, _target_percent
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    SolarForecastState,
)
from .tariff import TariffSettings

rolling = agile_rolling_planning.rolling_runtime
dispatch = agile_settlement_dispatch.dispatch_runtime
deadline_runtime = agile_deadline_guard.deadline_runtime

MIN_HEADROOM_FORECAST_CONFIDENCE_PERCENT = 70.0
HEADROOM_MIN_PRICE_ADVANTAGE_PENCE = 0.15
_EPSILON = 1e-6


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dt(value: Any) -> datetime | None:
    """Parse one timestamp and normalise it to UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _effective_precheap_target(
    config: SimulationConfig,
    forecast_plan: ForecastPlanState | None,
) -> tuple[float, float]:
    """Return normal and forecast-protected SOC targets."""
    normal = min(
        max(_target_percent(config), config.battery_reserve_percent, 0.0),
        100.0,
    )
    forecast = None
    if forecast_plan is not None and forecast_plan.ready:
        forecast = _number(forecast_plan.minimum_precheap_soc_percent)
    effective = min(max(normal, forecast if forecast is not None else normal), 100.0)
    return normal, effective


def _economic_export_floor_pence(tariff: TariffSettings) -> float:
    """Use the configured overnight import rate as the ordinary export floor."""
    return max(float(tariff.offpeak_rate_pence), 0.0)


def _forecast_confidence(
    forecast: SolarForecastState | None,
    forecast_plan: ForecastPlanState | None,
) -> float:
    """Return the conservative confidence shared by forecast and plan."""
    values = [
        value
        for value in (
            _number(getattr(forecast, "confidence_percent", None)),
            _number(getattr(forecast_plan, "confidence_percent", None)),
        )
        if value is not None and value > 0.0
    ]
    return min(values) if values else 0.0


def _conservative_house_kw(
    learned: LearnedState | None,
    forecast_plan: ForecastPlanState | None,
    *,
    now: datetime,
    deadline: datetime,
) -> float:
    """Estimate a deliberately conservative house load during solar hours."""
    typical = max(_number(getattr(learned, "typical_house_load_kw", None)) or 0.0, 0.0)
    remaining = _number(
        getattr(forecast_plan, "expected_house_remaining_today_kwh", None)
    )
    hours = max((deadline - now).total_seconds() / 3600.0, 0.25)
    average = max(remaining / hours, 0.0) if remaining is not None else 0.0
    return max(typical, average)


def _forecast_spill_projection(
    *,
    now: datetime,
    deadline: datetime,
    soc_percent: float | None,
    config: SimulationConfig,
    forecast: SolarForecastState | None,
    forecast_plan: ForecastPlanState | None,
    learned: LearnedState | None,
    effective_target_soc_percent: float,
) -> dict[str, Any]:
    """Project forced solar spill without assuming forecast solar for safety.

    The model is intentionally conservative. It uses the larger of the learned
    current-slot house load and the remaining-day average house load, honours the
    protected pre-cheap SOC floor, and ignores any solar hour that is already in
    the past. The result is used only to re-time existing export.
    """
    confidence = _forecast_confidence(forecast, forecast_plan)
    hourly = (
        tuple(getattr(forecast, "hourly", ()) or ()) if forecast is not None else ()
    )
    if (
        soc_percent is None
        or forecast is None
        or not forecast.ready
        or confidence < MIN_HEADROOM_FORECAST_CONFIDENCE_PERCENT
        or not hourly
        or deadline <= now
    ):
        return {
            "available": False,
            "state": "unavailable",
            "confidence_percent": round(confidence, 1),
            "reason": "waiting for high-confidence hourly solar and current SOC",
        }

    capacity = max(config.battery_capacity_kwh, 0.1)
    battery = capacity * min(max(soc_percent, 0.0), 100.0) / 100.0
    protected = capacity * min(max(effective_target_soc_percent, 0.0), 100.0) / 100.0
    charge_efficiency = max(config.charge_efficiency, 0.01)
    discharge_efficiency = max(config.discharge_efficiency, 0.01)
    house_kw = _conservative_house_kw(
        learned,
        forecast_plan,
        now=now,
        deadline=deadline,
    )

    spill_windows: list[dict[str, Any]] = []
    total_spill = 0.0
    now_utc = now.astimezone(UTC)
    deadline_utc = deadline.astimezone(UTC)
    for item in sorted(hourly, key=lambda value: value.timestamp):
        start = item.timestamp.astimezone(UTC)
        end = start + timedelta(hours=1)
        overlap_start = max(start, now_utc)
        overlap_end = min(end, deadline_utc)
        if overlap_end <= overlap_start:
            continue
        hours = (overlap_end - overlap_start).total_seconds() / 3600.0
        solar_ac = max(float(item.solar_energy_kwh), 0.0) * hours
        house_ac = house_kw * hours
        solar_to_house = min(solar_ac, house_ac)
        deficit_ac = max(house_ac - solar_to_house, 0.0)
        available_stored = max(battery - protected, 0.0)
        discharge_stored = min(
            deficit_ac / discharge_efficiency,
            available_stored,
        )
        battery -= discharge_stored

        surplus_ac = max(solar_ac - solar_to_house, 0.0)
        available_room = max(capacity - battery, 0.0)
        stored_from_solar = min(surplus_ac * charge_efficiency, available_room)
        battery += stored_from_solar
        spill_ac = max(surplus_ac - stored_from_solar / charge_efficiency, 0.0)
        if spill_ac > _EPSILON:
            total_spill += spill_ac
            spill_windows.append(
                {
                    "start": overlap_start.isoformat(),
                    "end": overlap_end.isoformat(),
                    "spill_kwh": round(spill_ac, 3),
                    "ending_soc_percent": round(100.0 * battery / capacity, 1),
                }
            )

    stored_headroom = total_spill * charge_efficiency
    export_equivalent = stored_headroom * discharge_efficiency
    return {
        "available": True,
        "state": "spill_expected" if total_spill > _EPSILON else "no_spill_expected",
        "confidence_percent": round(confidence, 1),
        "conservative_house_kw": round(house_kw, 3),
        "forecast_spill_kwh": round(total_spill, 3),
        "required_stored_headroom_kwh": round(stored_headroom, 3),
        "required_early_export_kwh": round(export_equivalent, 3),
        "first_spill_at": spill_windows[0]["start"] if spill_windows else None,
        "last_spill_end": spill_windows[-1]["end"] if spill_windows else None,
        "spill_windows": spill_windows,
        "safety_basis": "re-time existing export only; protected SOC is never lowered",
    }


def _slot_map(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(slot.get("valid_from") or ""): slot
        for slot in state.get("today_slots", [])
        if isinstance(slot, dict) and slot.get("valid_from")
    }


def _selected_allocations(plan: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in plan.get("selected_slots", []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("valid_from") or "")
        if not key:
            continue
        result[key] = max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
    return result


def _apply_floor_and_forecast_target(
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    config: SimulationConfig,
    tariff: TariffSettings,
    forecast_plan: ForecastPlanState | None,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Trim the inherited plan to the replacement-price and forecast SOC floors."""
    allocations = _selected_allocations(plan)
    slots = _slot_map(state)
    floor_pence = _economic_export_floor_pence(tariff)
    normal_target, effective_target = _effective_precheap_target(config, forecast_plan)
    inherited_target = _number(plan.get("target_soc_percent"))
    inherited_target = normal_target if inherited_target is None else inherited_target

    blocked_for_price = 0.0
    for key, allocation in list(allocations.items()):
        rate = _number((slots.get(key) or {}).get("rate_pence"))
        if rate is not None and rate + _EPSILON < floor_pence:
            blocked_for_price += allocation
            allocations[key] = 0.0

    inherited_exportable = max(
        _number(plan.get("exportable_battery_energy_kwh")) or 0.0,
        0.0,
    )
    additional_protected_stored = (
        max(effective_target - inherited_target, 0.0)
        * max(config.battery_capacity_kwh, 0.1)
        / 100.0
    )
    additional_protected_ac = additional_protected_stored * max(
        config.discharge_efficiency,
        0.01,
    )
    physically_exportable = max(inherited_exportable - additional_protected_ac, 0.0)

    planned = sum(allocations.values())
    trim = max(planned - physically_exportable, 0.0)
    if trim > _EPSILON:
        for key in sorted(
            allocations,
            key=lambda value: (
                _number((slots.get(value) or {}).get("rate_pence")) or 0.0,
                value,
            ),
        ):
            if trim <= _EPSILON:
                break
            allocation = allocations[key]
            reduction = min(allocation, trim)
            allocations[key] -= reduction
            trim -= reduction

    return allocations, {
        "normal_target_soc_percent": round(normal_target, 1),
        "effective_precheap_target_soc_percent": round(effective_target, 1),
        "forecast_floor_applied": effective_target > normal_target + _EPSILON,
        "forecast_minimum_precheap_soc_percent": _number(
            getattr(forecast_plan, "minimum_precheap_soc_percent", None)
        ),
        "forecast_protection_state": getattr(forecast_plan, "state", None),
        "economic_export_floor_pence": round(floor_pence, 5),
        "economic_floor_blocked_kwh": round(blocked_for_price, 3),
        "additional_forecast_protected_energy_kwh": round(
            additional_protected_stored,
            3,
        ),
        "physical_exportable_after_forecast_floor_kwh": round(
            physically_exportable,
            3,
        ),
    }


def _spill_reference_rate(
    state: dict[str, Any],
    projection: dict[str, Any],
) -> float | None:
    """Return the best price likely to be available while forced spill occurs."""
    windows = [
        (_dt(item.get("start")), _dt(item.get("end")))
        for item in projection.get("spill_windows", [])
        if isinstance(item, dict)
    ]
    rates: list[float] = []
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        start = _dt(slot.get("valid_from"))
        end = _dt(slot.get("valid_to"))
        rate = _number(slot.get("rate_pence"))
        if start is None or end is None or rate is None:
            continue
        if any(
            window_start is not None
            and window_end is not None
            and min(end, window_end) > max(start, window_start)
            for window_start, window_end in windows
        ):
            rates.append(max(rate, 0.0))
    return max(rates) if rates else None


def _retime_for_solar_headroom(
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
    """Move planned export earlier when that creates valuable solar headroom."""
    deadline = agile._next_cheap(now, tariff).astimezone(UTC)
    soc = rolling._current_agile_soc(state)
    projection = _forecast_spill_projection(
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
    }
    if not projection.get("available") or projection.get("state") != "spill_expected":
        return allocations, {}, evidence

    first_spill = _dt(projection.get("first_spill_at"))
    if first_spill is None or first_spill <= now.astimezone(UTC):
        evidence["reason"] = "forecast spill is already active or has passed"
        return allocations, {}, evidence

    slots = _slot_map(state)
    spill_rate = _spill_reference_rate(state, projection)
    floor_pence = _economic_export_floor_pence(tariff)
    if spill_rate is None:
        evidence["reason"] = "no Agile price evidence overlaps forecast spill"
        return allocations, {}, evidence

    existing_early = 0.0
    for key, allocation in allocations.items():
        slot = slots.get(key) or {}
        end = _dt(slot.get("valid_to"))
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
                "spill_reference_rate_pence": round(spill_rate, 5),
                "existing_pre_spill_export_kwh": round(existing_early, 3),
            }
        )
        return allocations, {}, evidence

    effective_kw = max(_number(plan.get("effective_discharge_kw")) or 0.0, 0.0)
    current_house_kw = rolling._current_house_headroom_kw(self, config)
    candidates: list[tuple[float, datetime, str, float]] = []
    now_utc = now.astimezone(UTC)
    for key, slot in slots.items():
        start = _dt(slot.get("valid_from"))
        end = _dt(slot.get("valid_to"))
        rate = _number(slot.get("rate_pence"))
        if start is None or end is None or rate is None:
            continue
        overlap_start = max(start, now_utc)
        overlap_end = min(end, first_spill)
        if overlap_end <= overlap_start:
            continue
        if rate + _EPSILON < floor_pence:
            continue
        if rate + _EPSILON < spill_rate + HEADROOM_MIN_PRICE_ADVANTAGE_PENCE:
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

    donors = [
        key
        for key, allocation in allocations.items()
        if allocation > _EPSILON
        and (_dt((slots.get(key) or {}).get("valid_from")) or now_utc) >= first_spill
    ]
    donor_available = sum(allocations[key] for key in donors)
    if not candidates or donor_available <= _EPSILON:
        evidence.update(
            {
                "state": "waiting_for_retimable_export",
                "reason": "no later planned export can be moved into a better pre-spill slot",
                "spill_reference_rate_pence": round(spill_rate, 5),
                "existing_pre_spill_export_kwh": round(existing_early, 3),
            }
        )
        return allocations, {}, evidence

    remaining = min(required, donor_available)
    additions: dict[str, float] = {}
    expected_gain = 0.0
    for rate, _, key, spare in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if remaining <= _EPSILON:
            break
        addition = min(spare, remaining)
        allocations[key] = allocations.get(key, 0.0) + addition
        additions[key] = additions.get(key, 0.0) + addition
        expected_gain += addition * max(rate - spill_rate, 0.0)
        remaining -= addition

    shifted = sum(additions.values())
    to_remove = shifted
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

    shifted -= max(to_remove, 0.0)
    if shifted <= _EPSILON:
        return allocations, {}, evidence

    evidence.update(
        {
            "active": True,
            "state": "headroom_retimed",
            "reason": "earlier Agile export is worth more than forecast forced solar spill",
            "spill_reference_rate_pence": round(spill_rate, 5),
            "economic_export_floor_pence": round(floor_pence, 5),
            "existing_pre_spill_export_kwh": round(existing_early, 3),
            "re_timed_export_kwh": round(shifted, 3),
            "expected_value_gain_pence": round(expected_gain, 2),
            "candidate_slots": [
                {
                    "valid_from": key,
                    "rate_pence": _number((slots.get(key) or {}).get("rate_pence")),
                    "added_export_kwh": round(value, 3),
                }
                for key, value in sorted(additions.items())
            ],
        }
    )
    return allocations, additions, evidence


def _write_allocations(
    state: dict[str, Any],
    plan: dict[str, Any],
    allocations: dict[str, float],
    additions: dict[str, float],
    *,
    now: datetime,
) -> None:
    """Write a reconciled allocation back into slots and plan metadata."""
    slots = _slot_map(state)
    previous = {
        str(item.get("valid_from") or ""): item
        for item in plan.get("selected_slots", [])
        if isinstance(item, dict)
    }
    touched = set(previous) | set(allocations)
    now_utc = now.astimezone(UTC)
    for key in touched:
        slot = slots.get(key)
        if slot is None:
            continue
        allocation = round(max(allocations.get(key, 0.0), 0.0), 3)
        start = _dt(slot.get("valid_from"))
        end = _dt(slot.get("valid_to"))
        slot["rolling_planned_battery_export_kwh"] = allocation
        if allocation > _EPSILON:
            action = (
                "planned battery export — forecast solar headroom"
                if additions.get(key, 0.0) > _EPSILON
                else "planned battery export — rolling replan"
            )
            slot["rolling_action"] = action
            if start is not None and start > now_utc:
                slot["battery_export_kwh"] = allocation
                slot["actions"] = [action]
        elif end is not None and end > now_utc:
            slot["rolling_action"] = "hold — economic/forecast replan"
            if start is not None and start > now_utc:
                slot["battery_export_kwh"] = 0.0
                slot["actions"] = ["hold — economic/forecast replan"]

    selected: list[dict[str, Any]] = []
    for key, allocation in allocations.items():
        if allocation <= _EPSILON:
            continue
        slot = slots.get(key) or {}
        prior = previous.get(key) or {}
        selected.append(
            {
                "valid_from": key,
                "label": slot.get("label") or prior.get("label"),
                "rate_pence": (
                    _number(slot.get("rate_pence")) if slot else prior.get("rate_pence")
                ),
                "planned_battery_export_kwh": round(allocation, 3),
                "deadline_forced": bool(prior.get("deadline_forced")),
                "solar_headroom_retimed": additions.get(key, 0.0) > _EPSILON,
            }
        )
    selected.sort(key=lambda item: str(item.get("valid_from") or ""))
    plan["selected_slots"] = selected
    planned = sum(item["planned_battery_export_kwh"] for item in selected)
    plan["planned_battery_export_kwh"] = round(planned, 3)
    exportable = max(_number(plan.get("exportable_battery_energy_kwh")) or 0.0, 0.0)
    plan["unallocated_exportable_kwh"] = round(max(exportable - planned, 0.0), 3)
    next_slot = next(
        (
            item
            for item in selected
            if (_dt(item.get("valid_from")) or now_utc) >= now_utc
        ),
        selected[0] if selected else None,
    )
    plan["next_export_slot"] = next_slot


def _forecast_deadline_context(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
    target_soc_percent: float,
) -> dict[str, Any]:
    """Recalculate the proven solar-aware deadline against the effective target."""
    soc = rolling._current_agile_soc(state)
    effective_kw = _effective_deadline_kw(config)
    deadline = agile._next_cheap(now, tariff).astimezone(UTC)
    now_utc = now.astimezone(UTC)
    if soc is None or effective_kw <= _EPSILON or deadline <= now_utc:
        return {"available": False, "mode": "unavailable"}

    capacity = max(config.battery_capacity_kwh, 0.1)
    efficiency = max(config.discharge_efficiency, 0.01)
    battery_kwh = capacity * min(max(soc, 0.0), 100.0) / 100.0
    target_kwh = capacity * min(max(target_soc_percent, 0.0), 100.0) / 100.0
    required_ac = max(battery_kwh - target_kwh, 0.0) * efficiency
    segments = deadline_runtime._capacity_segments(
        self,
        now=now,
        deadline=deadline,
        config=config,
    )
    remaining_capacity = sum(
        float(item.get("capacity_kwh") or 0.0) for item in segments
    )
    latest_safe = deadline_runtime._latest_safe_start(segments, required_ac)
    guard_minutes = int(deadline_runtime.DEADLINE_GUARD_MINUTES)
    guarded_start = (
        latest_safe - timedelta(minutes=guard_minutes)
        if latest_safe is not None
        else now_utc
    )
    reachable = remaining_capacity + 0.05 >= required_ac
    if required_ac <= 0.01:
        mode = "target_reached"
    elif not reachable:
        mode = "maximum_discharge"
    elif now_utc >= guarded_start:
        mode = "deadline_following"
    else:
        mode = "price_optimised"
    return {
        "available": True,
        "mode": mode,
        "target_soc_percent": round(target_soc_percent, 1),
        "required_discharge_kwh": round(required_ac, 3),
        "remaining_capacity_kwh": round(remaining_capacity, 3),
        "deadline_margin_kwh": round(remaining_capacity - required_ac, 3),
        "latest_safe_export_start": latest_safe.isoformat() if latest_safe else None,
        "guarded_latest_safe_export_start": guarded_start.isoformat(),
        "current_battery_headroom_kw": round(
            float(segments[0].get("battery_kw") or 0.0) if segments else effective_kw,
            3,
        ),
    }


def _planned_current_export_kw(
    state: dict[str, Any],
    *,
    now: datetime,
    effective_kw: float,
) -> float:
    slot = dispatch._current_slot(state, now)
    hours = dispatch._remaining_current_slot_hours(state, now)
    allocation = (
        _number(slot.get("rolling_planned_battery_export_kwh")) if slot else None
    )
    return (
        min(max((allocation or 0.0) / hours, 0.0), effective_kw)
        if hours > _EPSILON
        else 0.0
    )


def _recalculate_dispatch(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> None:
    """Refresh current dispatch after allocation re-timing."""
    targets = dispatch._dispatch_targets(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )
    plan.update(
        {
            "dispatch_mode": targets.get("mode"),
            "dispatch_action": targets.get("action"),
            "current_house_battery_kw": targets.get("house_battery_kw"),
            "current_battery_discharge_target_kw": targets.get(
                "battery_discharge_target_kw"
            ),
            "current_battery_export_target_kw": targets.get("battery_export_target_kw"),
            "required_average_discharge_kw": targets.get("required_average_kw"),
            "live_deadline_margin_kwh": targets.get("deadline_margin_kwh"),
            "forecast_protected_deadline": targets.get("forecast_protected_deadline"),
        }
    )
    slot = dispatch._current_slot(state, now)
    hours = dispatch._remaining_current_slot_hours(state, now)
    export_target = _number(targets.get("battery_export_target_kw"))
    if slot is not None and export_target is not None:
        slot["rolling_target_battery_export_kw"] = round(export_target, 3)
        slot["rolling_target_total_discharge_kw"] = targets.get(
            "battery_discharge_target_kw"
        )
        slot["rolling_action"] = targets.get("action")
        slot["rolling_planned_battery_export_kwh"] = round(export_target * hours, 3)


def install_forecast_arbitrage() -> None:
    """Install forecast-floor, economic-floor, and solar-headroom reconciliation."""
    update = runtime.EfficientAgileSmartExportManager.async_update
    if not getattr(update, "_kems_forecast_arbitrage", False):
        original_update = update

        async def update_with_forecast_arbitrage(
            self,
            *,
            records,
            now,
            config,
            learned,
            forecast,
            forecast_plan,
            tariff,
        ):
            self._kems_forecast_arbitrage_forecast = forecast
            self._kems_forecast_arbitrage_plan = forecast_plan
            self._kems_forecast_arbitrage_learned = learned
            return await original_update(
                self,
                records=records,
                now=now,
                config=config,
                learned=learned,
                forecast=forecast,
                forecast_plan=forecast_plan,
                tariff=tariff,
            )

        update_with_forecast_arbitrage._kems_forecast_arbitrage = True
        runtime.EfficientAgileSmartExportManager.async_update = (
            update_with_forecast_arbitrage
        )

    current_dispatch = dispatch._dispatch_targets
    if not getattr(current_dispatch, "_kems_forecast_arbitrage", False):
        original_dispatch = current_dispatch

        def dispatch_with_forecast_arbitrage(
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

            forecast_plan = getattr(self, "_kems_forecast_arbitrage_plan", None)
            normal_target, effective_target = _effective_precheap_target(
                config,
                forecast_plan,
            )
            floor_pence = _economic_export_floor_pence(tariff)
            targets["normal_target_soc_percent"] = round(normal_target, 1)
            targets["target_soc_percent"] = round(effective_target, 1)
            targets["economic_export_floor_pence"] = round(floor_pence, 5)

            if plan.get("price_horizon_battery_export_held") or plan.get(
                "dispatch_blocked_for_price_horizon"
            ):
                return targets

            current_slot = dispatch._current_slot(state, now)
            current_rate = (
                _number(current_slot.get("rate_pence"))
                if isinstance(current_slot, dict)
                else None
            )
            house_kw = max(_number(targets.get("house_battery_kw")) or 0.0, 0.0)
            if current_rate is not None and current_rate + _EPSILON < floor_pence:
                targets.update(
                    {
                        "mode": "economic_floor_hold",
                        "action": (
                            "hold battery export — Agile price is below the overnight "
                            "replacement rate; house remains first"
                        ),
                        "battery_export_target_kw": 0.0,
                        "battery_discharge_target_kw": round(house_kw, 3),
                        "economic_floor_active": True,
                    }
                )
                return targets

            if effective_target <= normal_target + _EPSILON:
                return targets

            guard = _forecast_deadline_context(
                self,
                state,
                now=now,
                config=config,
                tariff=tariff,
                target_soc_percent=effective_target,
            )
            targets["forecast_protected_deadline"] = guard
            if not guard.get("available"):
                return targets

            mode = str(guard.get("mode") or "price_optimised")
            effective_kw = max(
                _number(targets.get("effective_discharge_kw")) or 0.0, 0.0
            )
            if mode == "target_reached":
                targets.update(
                    {
                        "mode": "forecast_floor_reached",
                        "action": (
                            "forecast pre-cheap SOC floor reached — no deliberate "
                            "battery export; house remains first"
                        ),
                        "battery_export_target_kw": 0.0,
                        "battery_discharge_target_kw": round(house_kw, 3),
                        "deadline_margin_kwh": guard.get("deadline_margin_kwh"),
                    }
                )
                return targets

            if mode == "price_optimised":
                planned_export_kw = _planned_current_export_kw(
                    state,
                    now=now,
                    effective_kw=effective_kw,
                )
                export_kw = min(
                    planned_export_kw,
                    max(config.export_limit_kw, 0.0),
                    max(config.inverter_limit_kw - house_kw, 0.0),
                    max(config.max_discharge_kw - house_kw, 0.0),
                )
                total_kw = min(house_kw + export_kw, effective_kw)
                targets.update(
                    {
                        "mode": "forecast_protected_price_optimised",
                        "action": (
                            "price-optimised export above forecast pre-cheap SOC floor; "
                            "house first"
                        ),
                        "planned_price_export_kw": round(export_kw, 3),
                        "battery_export_target_kw": round(
                            max(total_kw - house_kw, 0.0), 3
                        ),
                        "battery_discharge_target_kw": round(total_kw, 3),
                        "deadline_margin_kwh": guard.get("deadline_margin_kwh"),
                    }
                )
                return targets

            safe_battery_kw = min(
                max(_number(guard.get("current_battery_headroom_kw")) or 0.0, 0.0),
                max(config.max_discharge_kw, 0.0),
            )
            protected_house_kw = min(house_kw, safe_battery_kw)
            export_kw = min(
                max(safe_battery_kw - protected_house_kw, 0.0),
                max(config.export_limit_kw, 0.0),
                max(config.inverter_limit_kw - protected_house_kw, 0.0),
                max(config.max_discharge_kw - protected_house_kw, 0.0),
            )
            total_kw = protected_house_kw + export_kw
            targets.update(
                {
                    "mode": f"forecast_protected_{mode}",
                    "action": (
                        "forecast-protected deadline discharge — preserve the higher "
                        "pre-cheap SOC floor; house first"
                    ),
                    "house_battery_kw": round(protected_house_kw, 3),
                    "battery_export_target_kw": round(export_kw, 3),
                    "battery_discharge_target_kw": round(total_kw, 3),
                    "deadline_margin_kwh": guard.get("deadline_margin_kwh"),
                }
            )
            return targets

        dispatch_with_forecast_arbitrage._kems_forecast_arbitrage = True
        dispatch._dispatch_targets = dispatch_with_forecast_arbitrage

    current_plan = rolling._rolling_plan
    if not getattr(current_plan, "_kems_forecast_arbitrage", False):
        original_plan = current_plan

        def rolling_plan_with_forecast_arbitrage(
            self,
            state,
            *,
            now,
            config: SimulationConfig,
            tariff: TariffSettings,
        ):
            plan = original_plan(
                self,
                state,
                now=now,
                config=config,
                tariff=tariff,
            )
            if not isinstance(plan, dict) or not plan.get("available"):
                return plan

            forecast_plan = getattr(self, "_kems_forecast_arbitrage_plan", None)
            forecast = getattr(self, "_kems_forecast_arbitrage_forecast", None)
            learned = getattr(self, "_kems_forecast_arbitrage_learned", None)
            allocations, policy = _apply_floor_and_forecast_target(
                state,
                plan,
                config=config,
                tariff=tariff,
                forecast_plan=forecast_plan,
            )
            plan.update(policy)
            plan["target_soc_percent"] = policy["effective_precheap_target_soc_percent"]
            plan["exportable_battery_energy_kwh"] = policy[
                "physical_exportable_after_forecast_floor_kwh"
            ]
            allocations, additions, headroom = _retime_for_solar_headroom(
                self,
                state,
                plan,
                allocations,
                now=now,
                config=config,
                tariff=tariff,
                forecast=forecast,
                forecast_plan=forecast_plan,
                learned=learned,
                effective_target_soc_percent=policy[
                    "effective_precheap_target_soc_percent"
                ],
            )
            plan["forecast_solar_headroom"] = headroom
            plan["solar_headroom_active"] = bool(headroom.get("active"))
            plan["solar_headroom_retimed_kwh"] = headroom.get(
                "re_timed_export_kwh", 0.0
            )
            _write_allocations(
                state,
                plan,
                allocations,
                additions,
                now=now,
            )
            _recalculate_dispatch(
                self,
                state,
                plan,
                now=now,
                config=config,
                tariff=tariff,
            )
            return plan

        rolling_plan_with_forecast_arbitrage._kems_forecast_arbitrage = True
        rolling._rolling_plan = rolling_plan_with_forecast_arbitrage
