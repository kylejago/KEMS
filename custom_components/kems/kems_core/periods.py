"""Home Assistant-independent period aggregation for KEMS reporting."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .models import PeriodTotals

_PERIOD_METADATA_FIELDS = frozenset(
    {
        "start_date",
        "end_date",
        "days_included",
        "complete_days",
        "incomplete_days",
        "data_complete",
    }
)


def period_value_keys() -> tuple[str, ...]:
    """Return numeric PeriodTotals fields that can be summed."""
    return tuple(
        key
        for key in PeriodTotals.__dataclass_fields__
        if key not in _PERIOD_METADATA_FIELDS
    )


def period_value_kwargs(values: dict[str, float]) -> dict[str, float]:
    """Normalise a mapping into the numeric PeriodTotals payload."""
    return {key: round(float(values.get(key, 0.0)), 3) for key in period_value_keys()}


def summarise_period_records(
    records: dict[str, dict[str, float]],
    start: date,
    end: date,
    *,
    current_day: date,
) -> PeriodTotals:
    """Sum daily records for a bounded reporting period."""
    selected: list[tuple[date, dict[str, float]]] = []
    for day_text, values in records.items():
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            continue
        if start <= day <= end:
            selected.append((day, values))

    totals: dict[str, float] = defaultdict(float)
    valid_keys = set(period_value_keys())
    for _, values in selected:
        for key, value in values.items():
            if key in valid_keys:
                totals[key] += value

    selected_days = {day for day, _ in selected}
    complete_days = sum(
        1 for day, values in selected if day != current_day and bool(values)
    )
    incomplete_days = sum(
        1 for day, values in selected if day != current_day and not values
    )
    return PeriodTotals(
        start_date=start,
        end_date=end,
        days_included=len(selected_days),
        complete_days=complete_days,
        incomplete_days=incomplete_days,
        data_complete=incomplete_days == 0,
        **period_value_kwargs(totals),
    )
