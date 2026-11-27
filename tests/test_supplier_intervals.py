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


def test_migrate_automatic_gas_without_poisoning_csv_or_electricity():
    start = datetime(2026, 11, 24, tzinfo=UTC)
    gas = _row(start, 6.5, kind="gas")
    ledger = SupplierIntervalLedger()
    ledger.restore(
        {
            "format": "kems-supplier-intervals-v1",
            "rows": [
                {**gas, "source": "octopus_estimated_gas"},
                {**_row(start), "source": "octopus_integration"},
            ],
            "conflicts": [["gas", start.isoformat()]],
        },
        now=NOW,
    )
    assert ledger.summary()["gas_quarantine"]["retained_raw_intervals"] == 1
    assert ledger.summary()["kinds"]["gas"]["usable_intervals"] == 0
    assert ledger.ingest(
        [_row(start, 0.1, kind="gas")], source="octopus_csv", now=NOW
    )
    assert not ledger.ingest([gas], source="octopus_estimated_gas", now=NOW)
    assert ledger.summary()["kinds"]["gas"]["usable_intervals"] == 1
    assert ledger.summary()["kinds"]["electricity_import"]["usable_intervals"] == 1
    restored = SupplierIntervalLedger()
    restored.restore(ledger.dump(), now=NOW)
    assert restored.summary() == ledger.summary()


def test_gas_daily_reference_does_not_create_half_hours_or_accept_bad_totals():
    ledger = SupplierIntervalLedger()
    good = {"date": "2026-11-24", "daily_kwh": 6.5, "lifetime_delta_kwh": 6.5}
    assert ledger.ingest_gas_daily_reference([good], now=NOW)
    assert not ledger.ingest_gas_daily_reference(
        [
            {**good, "date": "2026-11-25", "lifetime_delta_kwh": 160.689},
            {**good, "date": "2026-11-26"},
        ],
        now=NOW,
    )
    assert ledger.summary()["gas_quarantine"]["recent_daily_reference_kwh"] == {
        "2026-11-24": 6.5
    }
    assert ledger.summary()["kinds"]["gas"]["retained_intervals"] == 0
    assert ledger.ingest_gas_daily_reference(
        [{**good, "daily_kwh": 7.0, "lifetime_delta_kwh": 7.0}], now=NOW
    )
    assert ledger.summary()["gas_quarantine"]["recent_daily_reference_kwh"] == {}


def test_electricity_reconciliation_does_not_rewrite_or_infer_missing_days():
    ledger = SupplierIntervalLedger()
    start = datetime(2026, 11, 24, tzinfo=UTC)
    rows = [_row(start + timedelta(minutes=30 * n)) for n in range(48)] + [
        _row(start + timedelta(days=1))
    ]
    ledger.ingest(rows, source="octopus_csv", now=NOW)
    before = ledger.dump()
    result = ledger.electricity_reconciliation(
        {"2026-11-24": {"grid_import_kwh": 47.0}}, now=NOW
    )
    assert result["kinds"]["electricity_import"]["complete_supplier_days"] == 1
    assert result["kinds"]["electricity_import"]["net_difference_kwh"] == 1.0
    assert result["kinds"]["electricity_export"]["net_difference_kwh"] is None
    assert result["cost_or_roi_adjustment_authorised"] is False
    assert ledger.dump() == before
