"""Forecast-aware path-constrained scheduling for live Agile export.

The existing total-discharge ledger remains the fail-safe authority when forecast
evidence is unavailable or deadline escalation is active.  During ordinary
price optimisation, a high-confidence hourly solar forecast may extend that plan
through the pure chronological scheduler: future solar is credited only after it
arrives, deliberate export never drives the model below the optimiser target,
and every slot remains bounded by the existing five-minute shared-inverter
capacity model.

This layer changes simulation/shadow planning only.  Real hardware writes remain
blocked by the existing commissioning and backend gates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import agile_deadline_guard, agile_rolling_planning
from . import agile_smart_export as agile
from . import agile_total_discharge_ledger as total_ledger
from .kems_core import SimulationConfig
from .kems_core.forecast_path_scheduler import allocate_forecast_path_exports
from .tariff import TariffSettings

rolling = agile_rolling_planning.rolling_runtime
deadline_runtime = agile_deadline_guard.deadline_runtime
MIN_FORECAST_CONFIDENCE_PERCENT = 70.0
_EPSILON = 1e-6


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _dt(value: Any) -> datetime | None:
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


def _forecast_ready(self) -> tuple[bool, float]:
    forecast = getattr(self, "_kems_alpha734_forecast", None)
    confidence = _number(getattr(forecast, "confidence_percent", None)) or 0.0
    return bool(
        forecast is not None
        and getattr(forecast, "ready", False)
        and confidence >= MIN_FORECAST_CONFIDENCE_PERCENT
        and getattr(forecast, "hourly", ())
    ), confidence


def _apply_current_targets(
    self,
    plan: dict[str, Any],
    allocations,
    segments: list[dict[str, Any]],
    *,
    now: datetime,
    config: SimulationConfig,
    planning_house_kw: float,
) -> None:
    """Pace only the active path allocation while preserving live house-first use."""
    now_utc = now.astimezone(UTC)
    current = next(
        (
            item
            for item in allocations
            if item.valid_from <= now_utc < item.valid_to
        ),
        None,
    )
    if current is None:
        return

    segment = next(
        (
            item
            for item in segments
            if (_dt(item.get("start")) or now_utc)
            <= now_utc
            < (_dt(item.get("end")) or now_utc)
        ),
        segments[0] if segments else None,
    )
    if not isinstance(segment, dict):
        return

    battery_kw = max(_number(segment.get("battery_kw")) or 0.0, 0.0)
    solar_kw = max(_number(segment.get("solar_kw")) or 0.0, 0.0)
    house_kw = total_ledger._current_house_kw(self, planning_house_kw)
    solar_to_home_kw = min(house_kw, solar_kw)
    house_battery_kw = min(max(house_kw - solar_to_home_kw, 0.0), battery_kw)
    remaining_hours = max(
        (current.valid_to - now_utc).total_seconds() / 3600.0,
        _EPSILON,
    )
    paced_export_kw = min(
        current.planned_battery_export_kwh / remaining_hours,
        max(config.export_limit_kw, 0.0),
        max(battery_kw - house_battery_kw, 0.0),
    )
    total_kw = house_battery_kw + paced_export_kw
    plan["current_house_battery_kw"] = round(house_battery_kw, 3)
    plan["current_battery_export_target_kw"] = round(paced_export_kw, 3)
    plan["current_battery_discharge_target_kw"] = round(total_kw, 3)
    plan["dispatch_action"] = (
        "forecast-aware price optimisation; chronological SOC path; house first"
    )


def _apply_forecast_path(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Replace reserve-late export timing only when forecast path proof is valid."""
    if not plan.get("available"):
        return plan
    mode = str(plan.get("dispatch_mode") or "price_optimised")
    if mode in {"cheap_charge", "happy_hour_charge", "power_down_session"}:
        return plan
    guard = plan.get("deadline_guard")
    guard_mode = str(guard.get("mode") or "price_optimised") if isinstance(guard, dict) else "price_optimised"
    if guard_mode in {"deadline_following", "maximum_discharge"}:
        return plan

    ready, confidence = _forecast_ready(self)
    if not ready:
        plan["forecast_path_scheduler"] = {
            "available": False,
            "active": False,
            "confidence_percent": round(confidence, 1),
            "reason": "waiting for high-confidence hourly solar forecast",
            "hardware_writes": "blocked",
        }
        return plan

    soc = _number(plan.get("simulated_soc_percent"))
    target = _number(plan.get("target_soc_percent"))
    forecast_target = _number(plan.get("effective_precheap_target_soc_percent"))
    if soc is None or target is None:
        return plan
    if forecast_target is not None:
        target = max(target, forecast_target)

    deadline = agile._next_cheap(now, tariff).astimezone(UTC)
    segments = deadline_runtime._capacity_segments(
        self,
        now=now,
        deadline=deadline,
        config=config,
    )
    if not any(item.get("basis") == "KEMS hourly solar forecast" for item in segments):
        return plan

    planning_house_kw = total_ledger._planning_house_kw(self, plan)
    safety_headroom = (
        min(
            max(config.max_discharge_kw, 0.0),
            max(config.inverter_limit_kw, 0.0),
        )
        * 0.5
    )
    path = allocate_forecast_path_exports(
        slots=list(state.get("today_slots", []) or []),
        capacity_segments=segments,
        now=now,
        deadline=deadline,
        battery_capacity_kwh=config.battery_capacity_kwh,
        soc_percent=soc,
        target_soc_percent=target,
        charge_efficiency=config.charge_efficiency,
        discharge_efficiency=config.discharge_efficiency,
        max_charge_kw=config.max_charge_kw,
        house_kw=planning_house_kw,
        export_limit_kw=config.export_limit_kw,
        minimum_export_rate_pence=max(float(tariff.offpeak_rate_pence), 0.0),
        safety_headroom_kwh=safety_headroom,
        excluded_windows=total_ledger._power_down_windows(plan),
    )
    evidence = path.to_dict()
    evidence.update(
        {
            "active": bool(path.available),
            "confidence_percent": round(confidence, 1),
            "selection_basis": (
                "highest Agile prices first, with every candidate replayed through "
                "chronological stored-energy, solar-arrival and SOC constraints"
            ),
            "future_solar_borrowing": False,
            "house_first": True,
            "shared_inverter_capacity": True,
            "economic_export_floor_pence": round(
                max(float(tariff.offpeak_rate_pence), 0.0), 5
            ),
            "hardware_writes": "blocked",
        }
    )
    plan["forecast_path_scheduler"] = evidence
    if not path.available or path.forecast_solar_stored_kwh <= _EPSILON:
        return plan

    by_start = {
        _dt(slot.get("valid_from")): slot
        for slot in state.get("today_slots", []) or []
        if isinstance(slot, dict) and _dt(slot.get("valid_from")) is not None
    }
    selected_export: list[dict[str, Any]] = []
    selected_total: list[dict[str, Any]] = []
    now_utc = now.astimezone(UTC)
    for allocation in path.allocations:
        slot = by_start.get(allocation.valid_from)
        if slot is None:
            continue
        slot["physical_battery_export_capacity_kwh"] = allocation.export_capacity_kwh
        slot["planned_total_battery_discharge_kwh"] = (
            allocation.planned_total_discharge_kwh
        )
        slot["planned_battery_to_home_kwh"] = allocation.planned_house_battery_kwh
        slot["rolling_planned_battery_export_kwh"] = (
            allocation.planned_battery_export_kwh
        )
        slot["rolling_replan_generated_at"] = now.isoformat()
        slot["forecast_path_constrained"] = True
        is_current = allocation.valid_from <= now_utc < allocation.valid_to

        if allocation.planned_total_discharge_kwh > _EPSILON:
            row = {
                "valid_from": allocation.valid_from.isoformat(),
                "valid_to": allocation.valid_to.isoformat(),
                "label": slot.get("label"),
                "rate_pence": allocation.rate_pence,
                "planned_total_battery_discharge_kwh": (
                    allocation.planned_total_discharge_kwh
                ),
                "planned_battery_to_home_kwh": allocation.planned_house_battery_kwh,
                "planned_battery_export_kwh": allocation.planned_battery_export_kwh,
                "physical_export_capacity_kwh": allocation.export_capacity_kwh,
                "total_discharge_ledger": True,
                "forecast_path_constrained": True,
            }
            selected_total.append(row)
            if allocation.planned_battery_export_kwh > _EPSILON:
                slot["rolling_action"] = (
                    "planned battery export — forecast path / price optimised"
                )
                if not is_current:
                    slot["battery_export_kwh"] = allocation.planned_battery_export_kwh
                    slot["actions"] = [slot["rolling_action"]]
                selected_export.append(dict(row))
            elif not is_current:
                slot["rolling_action"] = "battery to home — forecast path"
                slot["battery_export_kwh"] = 0.0
                slot["actions"] = ["battery to home"]
        elif not is_current and allocation.valid_from < deadline:
            slot["rolling_action"] = "hold — higher-value forecast path"
            slot["battery_export_kwh"] = 0.0
            slot["actions"] = ["hold — higher-value forecast path"]

    selected_export.sort(key=lambda item: _dt(item.get("valid_from")) or deadline)
    selected_total.sort(key=lambda item: _dt(item.get("valid_from")) or deadline)
    next_export = next(
        (
            item
            for item in selected_export
            if (_dt(item.get("valid_to")) or deadline) > now_utc
        ),
        None,
    )
    if isinstance(plan.get("total_discharge_ledger"), dict):
        plan["pre_forecast_path_total_discharge_ledger"] = dict(
            plan["total_discharge_ledger"]
        )
    plan.update(
        {
            "exportable_battery_energy_kwh": round(path.planned_battery_export_kwh, 3),
            "planned_battery_export_kwh": round(path.planned_battery_export_kwh, 3),
            "planned_total_battery_discharge_kwh": round(
                path.planned_total_discharge_kwh, 3
            ),
            "predicted_house_battery_discharge_kwh": round(
                path.planned_house_battery_kwh, 3
            ),
            "selected_slots": selected_export,
            "total_discharge_selected_slots": selected_total,
            "next_export_slot": dict(next_export) if next_export is not None else None,
            "forecast_path_scheduler_active": True,
            "forecast_path_expected_ending_soc_percent": round(
                path.ending_soc_percent, 3
            ),
            "forecast_path_minimum_soc_percent": round(path.minimum_soc_percent, 3),
            "forecast_path_future_capacity_margin_kwh": round(
                path.future_export_capacity_margin_kwh, 3
            ),
            "total_discharge_capacity_model": (
                "5-minute solar-aware shared-inverter total-discharge ledger plus "
                "high-confidence chronological forecast-energy path"
            ),
            "hardware_writes": "blocked",
        }
    )
    _apply_current_targets(
        self,
        plan,
        path.allocations,
        segments,
        now=now,
        config=config,
        planning_house_kw=planning_house_kw,
    )
    total_ledger._enforce_cheap_boundary(state, deadline)
    return plan


def _rolling_plan_with_forecast_path(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    plan = _original_rolling_plan(
        self,
        state,
        now=now,
        config=config,
        tariff=tariff,
    )
    if not isinstance(plan, dict):
        return plan
    return _apply_forecast_path(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )


def install_forecast_path_scheduler() -> None:
    """Install the path scheduler immediately after the total-discharge ledger."""
    global _original_rolling_plan

    planner = rolling._rolling_plan
    if getattr(planner, "_kems_forecast_path_scheduler", False):
        return
    _original_rolling_plan = planner
    _rolling_plan_with_forecast_path._kems_forecast_path_scheduler = True
    rolling._rolling_plan = _rolling_plan_with_forecast_path
