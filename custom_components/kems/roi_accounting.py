"""Deterministic financial-commissioning reconciliation for live ROI."""

from __future__ import annotations

from datetime import date
from typing import Any

_COMMISSIONED_VALUE_KEYS = (
    "actual_avoided_import_value_pence",
    "actual_system_value_pence",
)


def _number(value: Any) -> float:
    """Return a finite numeric value or zero."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number or number in (float("inf"), float("-inf")):
        return 0.0
    return number


def commissioned_actual_value_totals(
    daily_records: dict[str, dict[str, float]],
    *,
    commissioning_date: date | None,
    tracking_date: date | None = None,
    tracking_values: dict[str, float] | None = None,
) -> dict[str, float]:
    """Rebuild real system value from the explicitly selected financial start date.

    The retained day ledger is authoritative. This intentionally ignores every
    simulated/what-if field and preserves signed actual system value so a future
    paid Agile export slot can legitimately reduce value when its price is
    negative. Days before financial commissioning are never counted.
    """
    totals = {key: 0.0 for key in _COMMISSIONED_VALUE_KEYS}
    if commissioning_date is None:
        return totals

    for day_text, values in daily_records.items():
        if not isinstance(values, dict):
            continue
        try:
            day = date.fromisoformat(str(day_text))
        except ValueError:
            continue
        if day < commissioning_date:
            continue
        for key in _COMMISSIONED_VALUE_KEYS:
            totals[key] += _number(values.get(key))

    if (
        isinstance(tracking_date, date)
        and tracking_date >= commissioning_date
        and isinstance(tracking_values, dict)
    ):
        for key in _COMMISSIONED_VALUE_KEYS:
            totals[key] += _number(tracking_values.get(key))

    return {key: round(value, 6) for key, value in totals.items()}


async def async_reconcile_financial_commissioning(
    recorder: Any,
    commissioning_date: date | None,
) -> bool:
    """Make lifetime actual ROI match retained evidence from the financial start.

    This is deliberately separate from FoxESS/control commissioning. It changes
    only the two real financial-value counters and their financial commissioning
    date; measured energy, import cost, export income, simulation and hardware
    authority are untouched.
    """
    ledger = getattr(recorder, "_ledger", None)
    daily = getattr(recorder, "_daily_records", None)
    tracking_date = getattr(recorder, "_tracking_date", None)
    tracking_values = getattr(recorder, "_tracking_values", None)
    if ledger is None or not isinstance(daily, dict):
        return False

    totals = commissioned_actual_value_totals(
        daily,
        commissioning_date=commissioning_date,
        tracking_date=(tracking_date if isinstance(tracking_date, date) else None),
        tracking_values=(tracking_values if isinstance(tracking_values, dict) else None),
    )

    previous = (
        getattr(ledger, "commissioning_date", None),
        _number(getattr(ledger, "actual_avoided_import_value_pence", 0.0)),
        _number(getattr(ledger, "actual_system_value_pence", 0.0)),
    )
    current = (
        commissioning_date,
        totals["actual_avoided_import_value_pence"],
        totals["actual_system_value_pence"],
    )
    if previous == current:
        return False

    ledger.commissioning_date = commissioning_date
    ledger.actual_avoided_import_value_pence = current[1]
    ledger.actual_system_value_pence = current[2]

    save = getattr(recorder, "async_save", None)
    if callable(save):
        await save()
    return True
