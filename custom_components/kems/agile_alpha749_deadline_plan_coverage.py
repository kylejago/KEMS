"""Alpha7.49 deadline-guard and price-plan coverage reconciliation.

Alpha7.34 protects the 10% pre-cheap target with a solar-aware physical
latest-safe-start calculation. The rolling price plan uses a separate slot
capacity model. When those models disagree, the dashboard can claim that a
later price-selected slot is next while the deadline guard is already exporting.

Alpha7.49 only suppresses that early deadline escalation when the future
price-selected plan is also physically sufficient under the same solar-aware
shared-inverter model. If it is not sufficient, the deadline guard remains in
force and its required current export is inserted into the price plan while an
equal amount is removed from the lowest-value later selected slot. This keeps
the plan, current decision and economics internally consistent.

This remains simulation/shadow only. Real FoxESS hardware writes remain blocked.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_alpha717_dispatch as alpha717
from . import agile_alpha734_deadline_guard as alpha734
from .kems_core import SimulationConfig

_EPSILON = 1e-6
_COVERAGE_TOLERANCE_KWH = 0.05


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _datetime(value: Any) -> datetime | None:
    """Parse an ISO datetime as UTC."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value)).astimezone(UTC)
    except ValueError:
        return None


def _future_price_plan_coverage(
    self,
    plan: dict[str, Any],
    targets: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
) -> dict[str, Any]:
    """Prove whether KEMS can wait for the next selected economic slot."""
    guard = targets.get("deadline_guard")
    guard = dict(guard) if isinstance(guard, dict) else {}
    next_slot = plan.get("next_export_slot")
    next_slot = dict(next_slot) if isinstance(next_slot, dict) else {}

    required = max(_number(guard.get("required_discharge_kwh")) or 0.0, 0.0)
    next_start = _datetime(next_slot.get("valid_from"))
    deadline = _datetime(guard.get("deadline"))
    now_utc = now.astimezone(UTC)
    if next_start is None or deadline is None or next_start >= deadline:
        return {
            "available": False,
            "safe_to_wait": False,
            "reason": "no valid future selected slot/deadline pair",
        }

    if next_start <= now_utc + alpha717.timedelta(seconds=1):
        return {
            "available": True,
            "safe_to_wait": False,
            "reason": "the economic plan already selects the current slot",
            "next_selected_export_start": next_start.isoformat(),
        }

    segments = alpha734._capacity_segments(
        self,
        now=next_start,
        deadline=deadline,
        config=config,
    )
    future_capacity = sum(
        max(_number(item.get("capacity_kwh")) or 0.0, 0.0)
        for item in segments
        if isinstance(item, dict)
    )
    margin = future_capacity - required
    safe_to_wait = future_capacity + _COVERAGE_TOLERANCE_KWH >= required
    return {
        "available": True,
        "safe_to_wait": safe_to_wait,
        "reason": (
            "future selected price plan remains physically sufficient"
            if safe_to_wait
            else "future selected price plan lacks solar-aware discharge capacity"
        ),
        "required_discharge_kwh": round(required, 3),
        "future_solar_aware_capacity_kwh": round(future_capacity, 3),
        "future_capacity_margin_kwh": round(margin, 3),
        "next_selected_export_start": next_start.isoformat(),
        "coverage_tolerance_kwh": _COVERAGE_TOLERANCE_KWH,
        "capacity_model": "Alpha7.34 5-minute solar-aware shared-inverter headroom",
    }


def _selected_slot_start(row: dict[str, Any]) -> datetime:
    """Sort selected rows safely, putting malformed rows last."""
    value = _datetime(row.get("valid_from"))
    return value or datetime.max.replace(tzinfo=UTC)


def _rebalance_deadline_forced_current_slot(
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    export_target_kw: float,
) -> dict[str, Any]:
    """Move required early export from the lowest-value future selected slot."""
    current = alpha717._current_slot(state, now)
    if not isinstance(current, dict):
        return {"applied": False, "reason": "current Agile slot unavailable"}

    remaining_hours = alpha717._remaining_current_slot_hours(state, now)
    if remaining_hours <= _EPSILON or export_target_kw <= _EPSILON:
        return {"applied": False, "reason": "no current export energy to rebalance"}

    current_start = _datetime(current.get("valid_from"))
    if current_start is None:
        return {"applied": False, "reason": "current Agile slot has no valid start"}

    exportable = max(
        _number(plan.get("exportable_battery_energy_kwh")) or 0.0,
        0.0,
    )
    selected_source = plan.get("selected_slots")
    selected = [
        dict(item)
        for item in selected_source
        if isinstance(item, dict)
    ] if isinstance(selected_source, list) else []

    current_row = next(
        (
            item
            for item in selected
            if _datetime(item.get("valid_from")) == current_start
        ),
        None,
    )
    existing_current = max(
        _number(current_row.get("planned_battery_export_kwh")) or 0.0,
        0.0,
    ) if current_row is not None else 0.0
    desired_current = min(
        max(export_target_kw, 0.0) * remaining_hours,
        exportable,
    )
    desired_current = max(desired_current, existing_current)
    extra = max(desired_current - existing_current, 0.0)
    if extra <= _EPSILON:
        return {"applied": False, "reason": "economic plan already covers current export"}

    future_rows = [
        item
        for item in selected
        if (_datetime(item.get("valid_from")) or current_start) > current_start
    ]
    future_rows.sort(
        key=lambda item: (
            _number(item.get("rate_pence")) or 0.0,
            _selected_slot_start(item),
        )
    )
    available_to_move = sum(
        max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
        for item in future_rows
    )
    moved = min(extra, available_to_move)
    if moved <= _EPSILON:
        return {"applied": False, "reason": "no later selected export can be rebalanced"}

    remaining = moved
    reduced_labels: list[str] = []
    for item in future_rows:
        if remaining <= _EPSILON:
            break
        value = max(
            _number(item.get("planned_battery_export_kwh")) or 0.0,
            0.0,
        )
        reduction = min(value, remaining)
        item["planned_battery_export_kwh"] = round(value - reduction, 3)
        remaining -= reduction
        if reduction > _EPSILON:
            reduced_labels.append(str(item.get("label") or "unknown"))

    new_current = existing_current + moved
    if current_row is None:
        current_row = {
            "valid_from": current.get("valid_from"),
            "label": current.get("label"),
            "rate_pence": round(
                max(_number(current.get("rate_pence")) or 0.0, 0.0),
                5,
            ),
            "planned_battery_export_kwh": round(new_current, 3),
            "deadline_forced": True,
        }
        selected.append(current_row)
    else:
        current_row["planned_battery_export_kwh"] = round(new_current, 3)
        current_row["deadline_forced"] = True

    selected = [
        item
        for item in selected
        if max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
        > _EPSILON
    ]
    selected.sort(key=_selected_slot_start)

    allocation_by_start = {
        _datetime(item.get("valid_from")): max(
            _number(item.get("planned_battery_export_kwh")) or 0.0,
            0.0,
        )
        for item in selected
        if _datetime(item.get("valid_from")) is not None
    }
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        start = _datetime(slot.get("valid_from"))
        if start is None or start < current_start:
            continue
        allocation = allocation_by_start.get(start, 0.0)
        slot["rolling_planned_battery_export_kwh"] = round(allocation, 3)
        if start == current_start and allocation > _EPSILON:
            slot["rolling_action"] = "deadline-required export — economic plan rebalanced"
        elif allocation > _EPSILON:
            slot["rolling_action"] = "planned battery export — rolling replan"
            slot["battery_export_kwh"] = round(allocation, 3)
            slot["actions"] = ["planned battery export — rolling replan"]
        else:
            slot["rolling_action"] = "hold — rolling replan"
            slot["battery_export_kwh"] = 0.0
            slot["actions"] = ["hold — rolling replan"]

    planned = sum(
        max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
        for item in selected
    )
    next_slot = next(
        (
            item
            for item in selected
            if (_datetime(item.get("valid_from")) or current_start) >= current_start
        ),
        selected[0] if selected else None,
    )
    plan.update(
        {
            "selected_slots": selected,
            "next_export_slot": next_slot,
            "planned_battery_export_kwh": round(planned, 3),
            "required_in_current_slot_kwh": round(new_current, 3),
            "unallocated_exportable_kwh": round(max(exportable - planned, 0.0), 3),
            "deadline_plan_rebalanced": True,
            "deadline_rebalanced_current_export_kwh": round(moved, 3),
            "deadline_rebalanced_from_future_labels": reduced_labels,
            "deadline_rebalance_policy": (
                "required early export replaces lowest-value later selected export"
            ),
        }
    )
    return {
        "applied": True,
        "moved_kwh": round(moved, 3),
        "current_slot": current.get("label"),
        "reduced_future_labels": reduced_labels,
    }


def _dispatch_with_alpha749(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff,
) -> dict[str, Any]:
    """Reconcile economic-plan coverage with a deadline-following escalation."""
    targets = alpha749_original_dispatch(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )
    if not isinstance(targets, dict):
        return targets
    if str(targets.get("mode") or "") != "deadline_following":
        return targets
    if "deadline_guard_escalated_from" not in targets:
        return targets

    coverage = _future_price_plan_coverage(
        self,
        plan,
        targets,
        now=now,
        config=config,
    )
    targets["economic_deadline_coverage"] = coverage
    plan["economic_deadline_coverage"] = coverage

    guard = targets.get("deadline_guard")
    guard = dict(guard) if isinstance(guard, dict) else {}
    if coverage.get("safe_to_wait"):
        house_kw = max(_number(targets.get("house_battery_kw")) or 0.0, 0.0)
        planned_export_kw = max(
            _number(targets.get("planned_price_export_kw")) or 0.0,
            0.0,
        )
        evidence = targets.get("solar_aware_inverter_headroom")
        evidence = dict(evidence) if isinstance(evidence, dict) else {}
        safe_battery_kw = _number(evidence.get("battery_inverter_headroom_kw"))
        if safe_battery_kw is None:
            safe_battery_kw = max(config.max_discharge_kw, 0.0)
        export_kw = min(
            planned_export_kw,
            max(safe_battery_kw - house_kw, 0.0),
            max(config.export_limit_kw, 0.0),
            max(config.inverter_limit_kw - house_kw, 0.0),
            max(config.max_discharge_kw - house_kw, 0.0),
        )
        total_kw = house_kw + export_kw
        action = (
            "price-selected battery export — future plan physically covers target"
            if export_kw > _EPSILON
            else "hold battery — future price-selected plan physically covers target"
        )
        targets.update(
            {
                "mode": "price_optimised",
                "action": action,
                "battery_export_target_kw": round(export_kw, 3),
                "battery_discharge_target_kw": round(total_kw, 3),
                "deadline_guard_suppressed_by_plan_coverage": True,
            }
        )
        guard.update(
            {
                "raw_mode": guard.get("mode"),
                "mode": "price_optimised",
                "deadline_guard_active": False,
                "suppressed_by_economic_plan_coverage": True,
                "economic_deadline_coverage": coverage,
            }
        )
        plan["deadline_guard_suppressed_by_plan_coverage"] = True
        if evidence:
            evidence["deadline_guard_applied"] = False
            evidence["economic_plan_coverage_override"] = True
            targets["solar_aware_inverter_headroom"] = evidence
    else:
        rebalance = _rebalance_deadline_forced_current_slot(
            state,
            plan,
            now=now,
            export_target_kw=max(
                _number(targets.get("battery_export_target_kw")) or 0.0,
                0.0,
            ),
        )
        plan["deadline_plan_rebalance"] = rebalance
        targets["deadline_plan_rebalance"] = rebalance
        guard.update(
            {
                "deadline_guard_active": True,
                "suppressed_by_economic_plan_coverage": False,
                "economic_deadline_coverage": coverage,
                "deadline_plan_rebalance": rebalance,
            }
        )

    targets["deadline_guard"] = guard
    self._kems_alpha734_deadline_guard = dict(guard)
    return targets


def install_alpha749_deadline_plan_coverage_patch() -> None:
    """Install final economic/deadline reconciliation after Alpha7.48."""
    dispatch = alpha717._dispatch_targets
    if getattr(dispatch, "_kems_alpha749_deadline_plan_coverage", False):
        return

    global alpha749_original_dispatch
    alpha749_original_dispatch = dispatch
    _dispatch_with_alpha749._kems_alpha749_deadline_plan_coverage = True
    alpha717._dispatch_targets = _dispatch_with_alpha749
