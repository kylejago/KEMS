"""Home Assistant-independent period aggregation for KEMS reporting."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .models import PeriodTotals

PERIOD_DATA_COMPLETE_KEY = "__data_complete"

# A saved numeric daily ledger field is evidence that a calculated total is
# present, not independent proof that all physical meter intervals were read.
LEDGER_TOTAL_EVIDENCE_KEYS = (
    "grid_import_kwh",
    "grid_export_kwh",
    "solar_generation_kwh",
    "import_cost_pence",
    "export_income_pence",
)


def recorded_totals_present(values: dict[str, float]) -> bool:
    """Separate available saved totals from complete simulation replay."""
    if not values:
        return False
    # A newly observed day with zero replay coverage cannot establish any
    # metered total, even though _current_values emits zero placeholders.
    if values.get("__data_coverage_percent", 1.0) <= 0:
        return False
    return any(key in values for key in LEDGER_TOTAL_EVIDENCE_KEYS)


_PERIOD_METADATA_FIELDS = frozenset(
    {
        "start_date",
        "end_date",
        "days_included",
        "complete_days",
        "incomplete_days",
        "data_complete",
        "recorded_totals_available",
        "recorded_days_with_totals",
        "simulation_coverage_complete",
        "simulation_complete_days",
        "simulation_incomplete_days",
        "independent_meter_completeness",
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

    def record_complete(values: dict[str, float]) -> bool:
        if not values:
            return False
        return values.get(PERIOD_DATA_COMPLETE_KEY, 1.0) >= 0.5

    complete_days = sum(
        1 for day, values in selected if day != current_day and record_complete(values)
    )
    incomplete_days = sum(
        1
        for day, values in selected
        if day != current_day and not record_complete(values)
    )
    data_complete = all(record_complete(values) for _, values in selected)
    recorded_days = sum(
        1 for _, values in selected if recorded_totals_present(values)
    )
    return PeriodTotals(
        start_date=start,
        end_date=end,
        days_included=len(selected_days),
        complete_days=complete_days,
        incomplete_days=incomplete_days,
        data_complete=data_complete,
        recorded_totals_available=recorded_days > 0,
        recorded_days_with_totals=recorded_days,
        simulation_coverage_complete=data_complete,
        simulation_complete_days=complete_days,
        simulation_incomplete_days=incomplete_days,
        independent_meter_completeness="not_verified",
        **period_value_kwargs(totals),
    )
