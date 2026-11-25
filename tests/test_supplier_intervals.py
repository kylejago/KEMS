"""Actual supplier intervals remain independent of existing financial totals."""

from datetime import UTC, datetime, timedelta

from kems_core.supplier_intervals import SupplierIntervalLedger

NOW = datetime(2026, 11, 26, tzinfo=UTC)


def _row(start, energy=1.0, kind="electricity_import"):
    return {
        "kind": kind,
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=30)).isoformat(),
        "kwh": energy,
    }


def test_idempotent_ingestion_and_conflicts_preserve_first_observation():
    ledger = SupplierIntervalLedger()
    start = datetime(2026, 11, 24, tzinfo=UTC)
    first = _row(start)
    source = "octopus_csv"
    assert ledger.ingest([first], source=source, now=NOW)
    assert not ledger.ingest([first], source=source, now=NOW)
    assert ledger.ingest([_row(start + timedelta(hours=1))], source=source, now=NOW)
    assert ledger.ingest([_row(start, 2.0)], source=source, now=NOW)
    result = ledger.summary()["kinds"]["electricity_import"]
    assert result["retained_intervals"] == 2
    assert result["usable_intervals"] == 1
    assert result["missing_or_conflicting_within_retained_span"] == 2
    restored = SupplierIntervalLedger()
    restored.restore(ledger.dump(), now=NOW)
    assert restored.summary() == ledger.summary()
    assert restored.rows[("electricity_import", start.isoformat())]["kwh"] == 1.0


def test_fall_back_day_keeps_both_clock_hours_and_never_zero_fills():
    ledger = SupplierIntervalLedger()
    start = datetime(2026, 10, 24, 23, tzinfo=UTC)
    rows = [_row(start + timedelta(minutes=30 * n), 0.0) for n in range(50)]
    assert ledger.ingest(rows, source="octopus_csv", now=NOW)
    result = ledger.summary()["kinds"]["electricity_import"]
    assert result["complete_local_days"] == 1
    assert result["usable_intervals"] == 50
    assert result["recent_complete_day_totals_kwh"] == {"2026-10-25": 0.0}
    assert ledger.summary()["missing_intervals_zero_filled"] is False


def test_invalid_incomplete_and_future_intervals_rejected():
    ledger = SupplierIntervalLedger()
    start = NOW - timedelta(hours=1)
    invalid = [
        _row(start, float("nan")),
        _row(start, -1),
        _row(start, True),
        _row(NOW),
        _row(start.replace(tzinfo=None)),
        {**_row(start), "end": NOW.isoformat()},
    ]
    assert not ledger.ingest(invalid, source="octopus_csv", now=NOW)
    assert not ledger.rows
