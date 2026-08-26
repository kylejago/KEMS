"""Authoritative total-discharge ledger for the Agile pre-cheap deadline.

KEMS previously planned deliberate battery export after subtracting the full
protected future house-energy reserve. That made the price plan silently assume
all protected house energy would definitely leave the battery before cheap power.
When the house used less than that reserve, KEMS discovered the missing discharge
late and fell into deadline/maximum-discharge catch-up.

This final canonical layer keeps house protection as a reserve, but makes the SOC
deadline use one separate total-battery-discharge obligation. Price-selected
settlement slots are allocated against the same five-minute solar-aware physical
capacity as the deadline guard. Each selected slot then splits that total battery
discharge house-first and grid-export second. If actual house demand changes, the
current export split changes rather than the required total discharge.

The cheap-start boundary is exclusive: a settlement slot beginning at the cheap
start is charge territory and can never be published as a discharge/export slot.
Real hardware writes remain blocked.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_deadline_guard, agile_rolling_planning
from . import agile_smart_export as agile
from .kems_core import SimulationConfig
from .kems_core.discharge_slot_ledger import (
    allocate_total_discharge_slots,
    required_total_discharge_kwh,
)
from .tariff import TariffSettings

rolling = agile_rolling_planning.rolling_runtime
deadline_runtime = agile_deadline_guard.deadline_runtime
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


def _dt(value: Any) -> datetime | None:
    """Return one aware timestamp normalised to UTC."""
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


def _planning_house_kw(self, plan: dict[str, Any]) -> float:
    """Return the conservative house power used only for destination splitting."""
    evidence = plan.get("solar_net_house_protection")
    if isinstance(evidence, dict):
        value = _number(evidence.get("conservative_house_kw"))
        if value is not None and value > _EPSILON:
            return value
    value = _number(plan.get("physical_slot_capacity_house_kw"))
    if value is not None:
        return max(value, 0.0)
    records = list(getattr(self, "_panel_today_records", []) or [])
    if records:
        value = _number(getattr(records[-1], "house_load_kw", None))
        if value is not None:
            return max(value, 0.0)
    return 0.0


def _current_house_kw(self, fallback: float) -> float:
    """Return current observed house power for the live house/export split."""
    records = list(getattr(self, "_panel_today_records", []) or [])
    if records:
        value = _number(getattr(records[-1], "house_load_kw", None))
        if value is not None:
            return max(value, 0.0)
    return max(fallback, 0.0)


def _power_down_context(plan: dict[str, Any]) -> dict[str, Any]:
    value = plan.get("power_down_priority")
    return dict(value) if isinstance(value, dict) else {}


def _power_down_windows(plan: dict[str, Any]) -> tuple[tuple[datetime, datetime], ...]:
    """Return the absolute-priority Power Down window reserved from normal Agile."""
    context = _power_down_context(plan)
    if not context.get("available"):
        return ()
    start = _dt(context.get("start"))
    end = _dt(context.get("end"))
    if start is None or end is None or end <= start:
        return ()
    return ((start, end),)


def _power_down_discharge_credit(plan: dict[str, Any]) -> float:
    """Credit only the explicit reserved event export against normal discharge.

    Event house demand is deliberately not treated as guaranteed future battery
    discharge. The reserved export is an explicit KEMS event command and is the
    conservative amount ordinary Agile may rely on while keeping Power Down
    absolute priority.
    """
    context = _power_down_context(plan)
    if (
        not context.get("available")
        or context.get("active")
        or not context.get("reserve_required_before_next_cheap")
    ):
        return 0.0
    return max(_number(context.get("reserved_export_energy_kwh")) or 0.0, 0.0)


def _slot_map(state: dict[str, Any]) -> dict[datetime, dict[str, Any]]:
    """Return Today rows keyed by settlement start."""
    output: dict[datetime, dict[str, Any]] = {}
    for item in state.get("today_slots", []) or []:
        if not isinstance(item, dict):
            continue
        start = _dt(item.get("valid_from"))
        if start is not None:
            output[start] = item
    return output


def _enforce_cheap_boundary(state: dict[str, Any], deadline: datetime) -> None:
    """Make the cheap-start settlement slot charge-only in the published plan."""
    deadline_utc = deadline.astimezone(UTC)
    for slot in state.get("today_slots", []) or []:
        if not isinstance(slot, dict):
            continue
        start = _dt(slot.get("valid_from"))
        if start is None or start < deadline_utc:
            continue
        slot["rolling_planned_battery_export_kwh"] = 0.0
        slot["planned_total_battery_discharge_kwh"] = 0.0
        slot["planned_battery_to_home_kwh"] = 0.0
        slot["battery_export_kwh"] = 0.0
        slot["rolling_action"] = "cheap charge — overnight window"
        slot["actions"] = ["cheap charge"]


def _current_total_discharge_targets(
    *,
    allocations,
    capacity_segments: list[dict[str, Any]],
    now: datetime,
    house_kw: float,
    export_limit_kw: float,
) -> tuple[float, float, float] | None:
    """Pace the selected current total discharge, then split it house-first."""
    now_utc = now.astimezone(UTC)
    current = next(
        (
            item
            for item in allocations
            if item.valid_from <= now_utc < item.valid_to
            and item.planned_total_discharge_kwh > _EPSILON
        ),
        None,
    )
    if current is None:
        return None

    segment = next(
        (
            item
            for item in capacity_segments
            if (_dt(item.get("start")) or now_utc)
            <= now_utc
            < (_dt(item.get("end")) or now_utc)
        ),
        capacity_segments[0] if capacity_segments else None,
    )
    if not isinstance(segment, dict):
        return None

    solar_kw = max(_number(segment.get("solar_kw")) or 0.0, 0.0)
    battery_kw = max(_number(segment.get("battery_kw")) or 0.0, 0.0)
    remaining_hours = max(
        (current.valid_to - now_utc).total_seconds() / 3600.0,
        _EPSILON,
    )
    requested_total = min(
        current.planned_total_discharge_kwh / remaining_hours,
        battery_kw,
    )
    solar_to_home_kw = min(max(house_kw, 0.0), solar_kw)
    house_battery_kw = min(
        max(house_kw - solar_to_home_kw, 0.0),
        requested_total,
    )
    export_kw = min(
        max(requested_total - house_battery_kw, 0.0),
        max(export_limit_kw, 0.0),
        max(battery_kw - house_battery_kw, 0.0),
    )
    total_kw = house_battery_kw + export_kw
    return (
        round(house_battery_kw, 3),
        round(export_kw, 3),
        round(total_kw, 3),
    )


def _apply_total_discharge_ledger(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Make total battery discharge authoritative through the cheap deadline."""
    if not plan.get("available"):
        return plan

    deadline = agile._next_cheap(now, tariff).astimezone(UTC)
    _enforce_cheap_boundary(state, deadline)

    mode = str(plan.get("dispatch_mode") or "price_optimised")
    if mode in {"cheap_charge", "happy_hour_charge", "power_down_session"}:
        return plan

    soc = _number(plan.get("simulated_soc_percent"))
    target = _number(plan.get("target_soc_percent"))
    if soc is None or target is None or deadline <= now.astimezone(UTC):
        return plan

    required_total = required_total_discharge_kwh(
        battery_capacity_kwh=config.battery_capacity_kwh,
        soc_percent=soc,
        target_soc_percent=target,
        discharge_efficiency=config.discharge_efficiency,
    )
    power_down_credit = min(_power_down_discharge_credit(plan), required_total)
    normal_required = max(required_total - power_down_credit, 0.0)
    segments = deadline_runtime._capacity_segments(
        self,
        now=now,
        deadline=deadline,
        config=config,
    )
    planning_house_kw = _planning_house_kw(self, plan)
    safety_headroom = (
        min(
            max(config.max_discharge_kw, 0.0),
            max(config.inverter_limit_kw, 0.0),
        )
        * 0.5
    )
    ledger = allocate_total_discharge_slots(
        slots=list(state.get("today_slots", []) or []),
        capacity_segments=segments,
        now=now,
        deadline=deadline,
        required_discharge_kwh=normal_required,
        house_kw=planning_house_kw,
        export_limit_kw=config.export_limit_kw,
        safety_headroom_kwh=safety_headroom,
        excluded_windows=_power_down_windows(plan),
    )

    by_start = _slot_map(state)
    selected_export: list[dict[str, Any]] = []
    selected_total: list[dict[str, Any]] = []
    for allocation in ledger.allocations:
        slot = by_start.get(allocation.valid_from)
        if slot is None:
            continue
        slot["physical_total_discharge_capacity_kwh"] = (
            allocation.total_discharge_capacity_kwh
        )
        slot["physical_battery_export_capacity_kwh"] = allocation.export_capacity_kwh
        slot["planned_total_battery_discharge_kwh"] = (
            allocation.planned_total_discharge_kwh
        )
        slot["planned_battery_to_home_kwh"] = allocation.planned_house_battery_kwh
        slot["rolling_planned_battery_export_kwh"] = (
            allocation.planned_battery_export_kwh
        )
        slot["rolling_replan_generated_at"] = now.isoformat()
        is_current = allocation.valid_from <= now.astimezone(UTC) < allocation.valid_to

        if allocation.planned_total_discharge_kwh > _EPSILON:
            total_row = {
                "valid_from": allocation.valid_from.isoformat(),
                "valid_to": allocation.valid_to.isoformat(),
                "label": slot.get("label"),
                "rate_pence": allocation.rate_pence,
                "planned_total_battery_discharge_kwh": (
                    allocation.planned_total_discharge_kwh
                ),
                "planned_battery_to_home_kwh": allocation.planned_house_battery_kwh,
                "planned_battery_export_kwh": allocation.planned_battery_export_kwh,
                "physical_total_discharge_capacity_kwh": (
                    allocation.total_discharge_capacity_kwh
                ),
                "physical_export_capacity_kwh": allocation.export_capacity_kwh,
                "total_discharge_ledger": True,
            }
            selected_total.append(total_row)

            if allocation.planned_battery_export_kwh > _EPSILON:
                slot["rolling_action"] = (
                    "planned battery export — total-discharge ledger; house first"
                )
                if not is_current:
                    slot["battery_export_kwh"] = allocation.planned_battery_export_kwh
                    slot["actions"] = [
                        "planned battery export — total-discharge ledger; house first"
                    ]
                selected_export.append(dict(total_row))
            elif not is_current:
                slot["rolling_action"] = "battery to home — total-discharge ledger"
                slot["battery_export_kwh"] = 0.0
                slot["actions"] = ["battery to home"]
        elif not is_current and allocation.valid_from < deadline:
            slot["rolling_action"] = "hold — total-discharge / price replan"
            slot["battery_export_kwh"] = 0.0
            slot["actions"] = ["hold — rolling replan"]

    selected_export.sort(key=lambda item: _dt(item.get("valid_from")) or deadline)
    selected_total.sort(key=lambda item: _dt(item.get("valid_from")) or deadline)
    next_export = next(
        (
            item
            for item in selected_export
            if (_dt(item.get("valid_to")) or deadline) > now.astimezone(UTC)
        ),
        None,
    )

    legacy_exportable = _number(plan.get("exportable_battery_energy_kwh"))
    hours = max(
        (deadline - now.astimezone(UTC)).total_seconds() / 3600.0,
        _EPSILON,
    )
    deadline_margin = ledger.total_discharge_capacity_kwh - normal_required
    plan.update(
        {
            "legacy_reserve_limited_exportable_battery_energy_kwh": legacy_exportable,
            "exportable_battery_energy_kwh": ledger.planned_battery_export_kwh,
            "planned_battery_export_kwh": ledger.planned_battery_export_kwh,
            "planned_total_battery_discharge_kwh": (
                ledger.allocated_total_discharge_kwh + power_down_credit
            ),
            "predicted_house_battery_discharge_kwh": ledger.planned_house_battery_kwh,
            "selected_slots": selected_export,
            "total_discharge_selected_slots": selected_total,
            "next_export_slot": dict(next_export) if next_export is not None else None,
            "deadline_capacity_margin_kwh": round(deadline_margin, 3),
            "required_average_discharge_kw": round(normal_required / hours, 3),
            "total_discharge_ledger_active": True,
            "total_discharge_required_kwh": required_total,
            "power_down_reserved_discharge_credit_kwh": round(power_down_credit, 3),
            "normal_agile_total_discharge_required_kwh": round(normal_required, 3),
            "remaining_total_discharge_capacity_kwh": (
                ledger.total_discharge_capacity_kwh
            ),
            "total_discharge_deadline_margin_kwh": round(deadline_margin, 3),
            "total_discharge_unallocated_kwh": (ledger.unallocated_total_discharge_kwh),
            "required_total_discharge_in_current_slot_kwh": (
                ledger.required_current_total_discharge_kwh
            ),
            "total_discharge_capacity_model": (
                "5-minute solar-aware shared-inverter total-discharge ledger; "
                "house first; cheap-start exclusive"
            ),
            "total_discharge_ledger": ledger.to_dict(),
            "hardware_writes": "blocked",
        }
    )

    if mode not in {"deadline_following", "maximum_discharge"}:
        targets = _current_total_discharge_targets(
            allocations=ledger.allocations,
            capacity_segments=segments,
            now=now,
            house_kw=_current_house_kw(self, planning_house_kw),
            export_limit_kw=config.export_limit_kw,
        )
        if targets is not None:
            house_target, export_target, total_target = targets
            plan["current_house_battery_kw"] = house_target
            plan["current_battery_export_target_kw"] = export_target
            plan["current_battery_discharge_target_kw"] = total_target
            plan["dispatch_action"] = (
                "price-optimised total discharge; house first, export remainder"
            )

    _enforce_cheap_boundary(state, deadline)
    return plan


def _rolling_plan_with_total_discharge(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Wrap the final rolling plan with one authoritative discharge ledger."""
    plan = _original_rolling_plan(
        self,
        state,
        now=now,
        config=config,
        tariff=tariff,
    )
    if not isinstance(plan, dict):
        return plan
    return _apply_total_discharge_ledger(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )


def install_total_discharge_ledger() -> None:
    """Install the final total-discharge deadline authority once."""
    rolling_plan = rolling._rolling_plan
    if getattr(rolling_plan, "_kems_total_discharge_ledger", False):
        return

    global _original_rolling_plan
    _original_rolling_plan = rolling_plan
    _rolling_plan_with_total_discharge._kems_total_discharge_ledger = True
    rolling._rolling_plan = _rolling_plan_with_total_discharge
