"""Separate the financial date from the optional rolling replay window."""

from datetime import UTC, datetime
from types import SimpleNamespace

from kems_core.historical_scope import commissioning_history_scope


def test_financial_day_presence_excludes_partial_and_earlier_days():
    records = [
        SimpleNamespace(timestamp=datetime(2026, 9, day, 12, tzinfo=UTC))
        for day in (10, 12, 13, 13, 15, 16)
    ]
    result = commissioning_history_scope(
        configured_date="2026-09-12",
        records=records,
        now=datetime(2026, 9, 16, 18, tzinfo=UTC),
    )
    assert result["completed_financial_days_expected"] == 3
    assert result["completed_financial_days_with_native_observations"] == 2
    assert result["completed_financial_days_without_retained_native_observations"] == 1
    assert result["earlier_native_days_retained"] == 1
    assert result["physical_installation_date_verified"] is False
    assert result["historical_backfill_or_roi_changed"] is False


def test_no_commissioning_date_does_not_invent_installation_history():
    result = commissioning_history_scope(
        configured_date=None, records=[], now=datetime(2026, 9, 16, tzinfo=UTC)
    )
    assert result == {"status": "commissioning_date_unavailable"}
