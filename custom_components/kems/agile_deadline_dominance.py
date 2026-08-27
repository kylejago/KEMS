"""Final Agile deadline precedence after the total-discharge ledger.

The total-discharge ledger is the final economic allocation authority, but a
settlement-boundary transition can leave its current slot unselected even after
the live deadline guard has escalated to ``maximum_discharge``. In that state a
lower-priority hold must never survive as a zero battery command.

This canonical Alpha8 layer runs after the total-discharge ledger. It preserves
all existing safety gates, derives the instantaneous command from the same
five-minute solar-aware physical capacity model, routes the house first, and
reconciles the current published slot. Real hardware writes remain blocked.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_deadline_guard, agile_rolling_planning
from . import agile_smart_export as agile
from .kems_core import SimulationConfig
from .kems_core.deadline_dominance import maximum_discharge_targets
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


def _current_slot(state: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    now_utc = now.astimezone(UTC)
    for item in state.get("today_slots", []) or []:
        if not isinstance(item, dict):
            continue
        start = _dt(item.get("valid_from"))
        end = _dt(item.get("valid_to"))
        if start is not None and end is not None and start <= now_utc < end:
            return item
    return None


def _latest_house_kw(self) -> float:
    records = list(getattr(self, "_panel_today_records", []) or [])
    if not records:
        return 0.0
    return max(_number(getattr(records[-1], "house_load_kw", None)) or 0.0, 0.0)


def _current_capacity_segment(
    self,
    *,
    now: datetime,
    deadline: datetime,
    config: SimulationConfig,
) -> dict[str, Any] | None:
    now_utc = now.astimezone(UTC)
    segments = deadline_runtime._capacity_segments(
        self,
        now=now,
        deadline=deadline,
        config=config,
    )
    for item in segments:
        if not isinstance(item, dict):
            continue
        start = _dt(item.get("start"))
        end = _dt(item.get("end"))
        if start is not None and end is not None and start <= now_utc < end:
            return item
    return segments[0] if segments and isinstance(segments[0], dict) else None


def _reconcile_current_slot(
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    house_kw: float,
    export_kw: float,
    total_kw: float,
) -> None:
    """Publish the deadline-owned command into the active settlement row."""
    slot = _current_slot(state, now)
    if slot is None:
        return
    end = _dt(slot.get("valid_to"))
    start = _dt(slot.get("valid_from"))
    if end is None or start is None:
        return
    remaining_hours = max((end - now.astimezone(UTC)).total_seconds() / 3600.0, 0.0)
    export_kwh = max(export_kw, 0.0) * remaining_hours
    house_kwh = max(house_kw, 0.0) * remaining_hours
    total_kwh = max(total_kw, 0.0) * remaining_hours

    slot.update(
        {
            "rolling_target_battery_export_kw": round(export_kw, 3),
            "rolling_target_total_discharge_kw": round(total_kw, 3),
            "rolling_planned_battery_export_kwh": round(export_kwh, 3),
            "planned_total_battery_discharge_kwh": round(total_kwh, 3),
            "planned_battery_to_home_kwh": round(house_kwh, 3),
            "rolling_action": "maximum discharge — deadline dominance; house first",
            "actions": ["maximum discharge — deadline dominance; house first"],
        }
    )

    selected = [
        dict(item)
        for item in plan.get("selected_slots", []) or []
        if isinstance(item, dict)
    ]
    current = next(
        (item for item in selected if _dt(item.get("valid_from")) == start),
        None,
    )
    if export_kwh > _EPSILON:
        row = current if current is not None else {}
        row.update(
            {
                "valid_from": start.isoformat(),
                "valid_to": end.isoformat(),
                "label": slot.get("label"),
                "rate_pence": _number(slot.get("rate_pence")) or 0.0,
                "planned_total_battery_discharge_kwh": round(total_kwh, 3),
                "planned_battery_to_home_kwh": round(house_kwh, 3),
                "planned_battery_export_kwh": round(export_kwh, 3),
                "physical_total_discharge_capacity_kwh": round(total_kwh, 3),
                "physical_export_capacity_kwh": round(export_kwh, 3),
                "deadline_forced": True,
                "total_discharge_ledger": True,
            }
        )
        if current is None:
            selected.append(row)
    selected.sort(key=lambda item: _dt(item.get("valid_from")) or datetime.max.replace(tzinfo=UTC))
    if selected:
        plan["selected_slots"] = selected
        plan["next_export_slot"] = next(
            (
                dict(item)
                for item in selected
                if (_dt(item.get("valid_to")) or start) > now.astimezone(UTC)
            ),
            None,
        )
        plan["planned_battery_export_kwh"] = round(
            sum(max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0) for item in selected),
            3,
        )


def _apply_deadline_dominance(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Make an active maximum-discharge deadline decision command-authoritative."""
    if str(plan.get("dispatch_mode") or "") != "maximum_discharge":
        return plan

    guard = plan.get("deadline_guard")
    guard = dict(guard) if isinstance(guard, dict) else {}
    if not guard.get("deadline_guard_active"):
        return plan

    deadline = _dt(guard.get("deadline")) or agile._next_cheap(now, tariff).astimezone(UTC)
    segment = _current_capacity_segment(
        self,
        now=now,
        deadline=deadline,
        config=config,
    )
    if not isinstance(segment, dict):
        plan["maximum_discharge_plan_reconciled"] = False
        plan["deadline_dominance_reason"] = "current physical capacity unavailable"
        return plan

    export_held = bool(plan.get("price_horizon_battery_export_held"))
    export_allowed = bool(
        config.battery_export_enabled
        and config.export_tariff_status == "active"
        and not export_held
    )
    targets = maximum_discharge_targets(
        battery_headroom_kw=max(_number(segment.get("battery_kw")) or 0.0, 0.0),
        house_load_kw=_latest_house_kw(self),
        solar_kw=max(_number(segment.get("solar_kw")) or 0.0, 0.0),
        max_discharge_kw=config.max_discharge_kw,
        inverter_limit_kw=config.inverter_limit_kw,
        export_limit_kw=config.export_limit_kw,
        export_allowed=export_allowed,
    )

    plan.update(
        {
            "current_house_battery_kw": targets.battery_to_home_kw,
            "current_battery_export_target_kw": targets.battery_export_kw,
            "current_battery_discharge_target_kw": targets.total_discharge_kw,
            "dispatch_action": "maximum discharge — deadline dominance; house first",
            "maximum_discharge_plan_reconciled": True,
            "deadline_dominance_reconciled": True,
            "deadline_dominance_export_allowed": export_allowed,
            "hardware_writes": "blocked",
        }
    )
    guard.update(
        {
            "maximum_discharge_plan_reconciled": True,
            "deadline_dominance_reconciled": True,
            "deadline_dominance_total_discharge_kw": targets.total_discharge_kw,
            "deadline_dominance_battery_export_kw": targets.battery_export_kw,
        }
    )
    plan["deadline_guard"] = guard
    _reconcile_current_slot(
        state,
        plan,
        now=now,
        house_kw=targets.battery_to_home_kw,
        export_kw=targets.battery_export_kw,
        total_kw=targets.total_discharge_kw,
    )
    return plan


def _rolling_plan_with_deadline_dominance(
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
    return _apply_deadline_dominance(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )


def install_deadline_dominance() -> None:
    """Install final deadline precedence after the total-discharge ledger."""
    rolling_plan = rolling._rolling_plan
    if getattr(rolling_plan, "_kems_deadline_dominance", False):
        return

    global _original_rolling_plan
    _original_rolling_plan = rolling_plan
    _rolling_plan_with_deadline_dominance._kems_deadline_dominance = True
    rolling._rolling_plan = _rolling_plan_with_deadline_dominance
