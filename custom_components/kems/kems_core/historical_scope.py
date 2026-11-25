"""Financial commissioning history coverage, distinct from meter completeness."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

_LONDON = ZoneInfo("Europe/London")


def commissioning_history_scope(
    *, configured_date: Any, records: Any, now: datetime
) -> dict[str, Any]:
    """Report retained day presence only, not simulation or physical coverage.

    The configured financial commissioning date is a reporting boundary,
    not an independently verified hardware installation date. Earlier
    observations remain available to existing forecasting and replay.
    """
    today = now.astimezone(_LONDON).date()
    try:
        start = date.fromisoformat(str(configured_date))
    except (TypeError, ValueError):
        return {"status": "commissioning_date_unavailable"}
    if start >= today:
        return {"status": "no_completed_commissioned_days"}
    days = {
        item.timestamp.astimezone(_LONDON).date()
        for item in records
        if isinstance(getattr(item, "timestamp", None), datetime)
        and item.timestamp.tzinfo is not None
    }
    # KEMS's commissioning day may be partial. Exclude it and today from
    # the full-day denominator rather than labelling either as missing.
    first_full_day = start + timedelta(days=1)
    expected = max((today - first_full_day).days, 0)
    retained = {day for day in days if first_full_day <= day < today}
    return {
        "status": "reporting_only",
        "financial_commissioning_date": start.isoformat(),
        "first_full_financial_day": first_full_day.isoformat(),
        "completed_financial_days_expected": expected,
        "completed_financial_days_with_native_observations": len(retained),
        "completed_financial_days_without_retained_native_observations": (
            expected - len(retained)
        ),
        "earlier_native_days_retained": sum(day < start for day in days),
        "missing_native_days_are_not_missing_meter_intervals": True,
        "physical_installation_date_verified": False,
        "historical_backfill_or_roi_changed": False,
        "note": (
            "Day presence in the retained observation window only; older "
            "observations may have aged out. No missing meter energy inferred."
        ),
    }
