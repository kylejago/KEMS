"""Tariff-aware actual export accounting and safe unpaid-income repair."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .kems_core import SimulationState, Snapshot
from .product_types import (
    EXPORT_TARIFF_TYPE_AGILE,
    EXPORT_TARIFF_TYPE_FIXED,
    EXPORT_TARIFF_TYPE_NONE,
)

LONDON = ZoneInfo("Europe/London")
MAX_INTERVAL_HOURS = 0.5


def _number(value: Any) -> float | None:
    """Return one finite numeric value when available."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _agile_slots(state: dict[str, Any]) -> tuple[tuple[datetime, datetime, float], ...]:
    """Return published current-day Agile slots from manager state."""
    raw = state.get("today_slots")
    if not isinstance(raw, list):
        return ()
    slots: list[tuple[datetime, datetime, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rate = _number(item.get("rate_pence"))
        try:
            start = datetime.fromisoformat(str(item.get("valid_from")))
            end = datetime.fromisoformat(str(item.get("valid_to")))
        except (TypeError, ValueError):
            continue
        if rate is None or start.tzinfo is None or end.tzinfo is None or end <= start:
            continue
        slots.append((start, end, rate))
    return tuple(slots)


def _agile_rate_at(
    slots: tuple[tuple[datetime, datetime, float], ...],
    timestamp: datetime,
) -> float | None:
    """Return the Agile Outgoing price covering one observation timestamp."""
    return next(
        (
            rate
            for start, end, rate in slots
            if start <= timestamp.astimezone(start.tzinfo) < end
        ),
        None,
    )


def current_export_rate_pence(
    *,
    tariff_type: str,
    fixed_rate_pence: float,
    agile_state: dict[str, Any],
) -> float | None:
    """Return the user-visible current export rate for the selected tariff."""
    if tariff_type == EXPORT_TARIFF_TYPE_NONE:
        return 0.0
    if tariff_type == EXPORT_TARIFF_TYPE_FIXED:
        return max(float(fixed_rate_pence), 0.0)
    if tariff_type == EXPORT_TARIFF_TYPE_AGILE:
        rate = _number(agile_state.get("current_rate_pence"))
        return max(rate, 0.0) if rate is not None else None
    return None


def actual_export_income_pence(
    records: list[Snapshot],
    now: datetime,
    *,
    tariff_type: str,
    fixed_rate_pence: float,
    agile_state: dict[str, Any],
) -> float | None:
    """Value measured current-day export using the tariff actually selected.

    No-paid-export is always worth zero. Fixed export uses the configured fixed
    price. Agile Outgoing uses the published half-hour price covering every
    measured export interval and fails closed when a positive-export interval
    cannot be priced instead of silently falling back to the legacy 12p value.
    """
    if tariff_type == EXPORT_TARIFF_TYPE_NONE:
        return 0.0

    today = now.astimezone(LONDON).date()
    day_records = sorted(
        (
            item
            for item in records
            if item.timestamp.astimezone(LONDON).date() == today
        ),
        key=lambda item: item.timestamp,
    )
    if len(day_records) < 2:
        return 0.0

    slots = _agile_slots(agile_state) if tariff_type == EXPORT_TARIFF_TYPE_AGILE else ()
    total = 0.0
    for current, following in zip(day_records, day_records[1:], strict=False):
        hours = min(
            max((following.timestamp - current.timestamp).total_seconds(), 0.0)
            / 3600.0,
            MAX_INTERVAL_HOURS,
        )
        if hours <= 0 or "grid_export_kw" in current.stale_fields:
            continue
        export_kw = _number(current.grid_export_kw)
        if export_kw is None or export_kw <= 0:
            continue
        exported_kwh = export_kw * hours
        if tariff_type == EXPORT_TARIFF_TYPE_FIXED:
            rate = max(float(fixed_rate_pence), 0.0)
        elif tariff_type == EXPORT_TARIFF_TYPE_AGILE:
            rate = _agile_rate_at(slots, current.timestamp)
            if rate is None:
                return None
            rate = max(rate, 0.0)
        else:
            return None
        total += exported_kwh * rate
    return round(total, 2)


def revalue_actual_export_income(
    simulation: SimulationState,
    export_income_pence: float | None,
) -> SimulationState:
    """Return live actual financial fields reconciled to authoritative income."""
    if export_income_pence is None:
        return simulation
    income = round(max(float(export_income_pence), 0.0), 2)
    import_cost = simulation.actual_import_cost_pence
    actual_cost = (
        round(float(import_cost) - income, 2)
        if import_cost is not None
        else simulation.actual_cost_pence
    )
    avoided = simulation.actual_avoided_import_value_pence
    system_value = (
        round(float(avoided) + income, 2)
        if avoided is not None
        else simulation.actual_system_value_pence
    )
    saving = (
        round(float(actual_cost) - float(simulation.simulated_cost_pence), 2)
        if actual_cost is not None and simulation.simulated_cost_pence is not None
        else simulation.saving_pence
    )
    return replace(
        simulation,
        actual_export_income_pence=income,
        actual_cost_pence=actual_cost,
        actual_system_value_pence=system_value,
        saving_pence=saving,
    )


def _scrub_day(values: dict[str, float]) -> float:
    """Zero one persisted actual export-income value and return income removed."""
    income = _number(values.get("export_income_pence")) or 0.0
    if abs(income) <= 1e-9:
        return 0.0
    values["export_income_pence"] = 0.0
    avoided = _number(values.get("actual_avoided_import_value_pence"))
    if avoided is not None:
        values["actual_system_value_pence"] = avoided
    return income


async def async_repair_no_paid_export_income(recorder: Any) -> bool:
    """Remove impossible paid-export income from the retained live ledger.

    This intentionally leaves measured grid-export kWh and every simulated/
    what-if value untouched. The migration is idempotent and only runs while
    the user has explicitly selected ``No paid export``.
    """
    daily = getattr(recorder, "_daily_records", None)
    tracking = getattr(recorder, "_tracking_values", None)
    if not isinstance(daily, dict) or not isinstance(tracking, dict):
        return False

    changed = False
    removed_commissioned = 0.0
    ledger = getattr(recorder, "_ledger", None)
    commissioning = getattr(ledger, "commissioning_date", None)

    for day_text, values in daily.items():
        if not isinstance(values, dict):
            continue
        removed = _scrub_day(values)
        if not removed:
            continue
        changed = True
        if isinstance(commissioning, date):
            try:
                if date.fromisoformat(str(day_text)) >= commissioning:
                    removed_commissioned += removed
            except ValueError:
                pass

    tracking_date = getattr(recorder, "_tracking_date", None)
    removed = _scrub_day(tracking)
    if removed:
        changed = True
        if (
            isinstance(commissioning, date)
            and isinstance(tracking_date, date)
            and tracking_date >= commissioning
        ):
            removed_commissioned += removed

    if not changed:
        return False

    reconcile = getattr(recorder, "_reconcile_observed_totals", None)
    if callable(reconcile):
        reconcile()
    if ledger is not None and removed_commissioned:
        current = _number(getattr(ledger, "actual_system_value_pence", 0.0)) or 0.0
        ledger.actual_system_value_pence = current - removed_commissioned

    await recorder.async_save()
    return True
