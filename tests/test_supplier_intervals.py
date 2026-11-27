"""Actual supplier intervals remain independent of existing financial totals."""

from datetime import UTC, datetime, timedelta

from kems_core.supplier_intervals import (
    SupplierIntervalLedger,
    gas_calorific_value_diagnostic,
)

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
    assert ledger.ingest([_row(start, 0.1, kind="gas")], source="octopus_csv", now=NOW)
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


def test_gas_quarantine_compares_only_matching_unconflicted_intervals():
    ledger = SupplierIntervalLedger()
    start = datetime(2026, 11, 24, tzinfo=UTC)
    ledger.ingest([_row(start, 0.5, kind="gas")], source="octopus_csv", now=NOW)
    ledger.ingest(
        [_row(start, 5.0, kind="gas")], source="octopus_estimated_gas", now=NOW
    )
    report = ledger.gas_quarantine_comparison()
    assert report["matched_nonconflicting_intervals"] == 1
    assert report["recent_overlap_days"][0]["difference_kwh"] == 4.5
    assert report["recent_overlap_days"][0]["nonzero_matched_intervals"] == 1
    assert report["recent_raw_days"][0]["raw_first_seen_kwh"] == 5.0
    assert report["automatic_gas_financially_usable"] is False
    ledger.ingest(
        [_row(start, 6.0, kind="gas")], source="octopus_estimated_gas", now=NOW
    )
    assert ledger.gas_quarantine_comparison()["matched_nonconflicting_intervals"] == 0


def test_paired_gas_volume_is_retained_but_never_promoted():
    ledger = SupplierIntervalLedger()
    start = NOW - timedelta(days=1)
    raw = _row(start, 11.2, kind="gas")
    assert ledger.ingest([raw], source="octopus_estimated_gas", now=NOW)
    paired = {**raw, "consumption_m3": 1.0}
    assert ledger.ingest([paired], source="octopus_estimated_gas", now=NOW)
    assert not ledger.ingest([paired], source="octopus_estimated_gas", now=NOW)
    ledger.ingest([_row(start, 1.0, kind="gas")], source="octopus_csv", now=NOW)
    result = ledger.gas_quarantine_comparison()
    assert result["paired_nonzero_observations"] == 1
    row = result["recent_paired_nonzero_observations"][0]
    assert row["automatic_m3"] == 1.0
    assert row["automatic_kwh"] == 11.2
    assert row["observed_kwh_per_m3"] == 11.2
    assert row["csv_kwh"] == 1.0
    assert result["conversion_validated"] is False
    assert result["automatic_gas_financially_usable"] is False
    restored = SupplierIntervalLedger()
    restored.restore(ledger.dump(), now=NOW)
    assert restored.gas_quarantine_comparison() == result
    assert restored.ingest(
        [{**paired, "consumption_m3": 2.0}],
        source="octopus_estimated_gas",
        now=NOW,
    )
    assert restored.gas_quarantine_comparison()["matched_nonconflicting_intervals"] == 0


def test_gas_conversion_diagnostic_never_corrects_provider_data():
    audit = gas_calorific_value_diagnostic({"calorific_value": 975})
    assert audit["provider_calorific_value"] == 975
    assert abs(audit["expected_kwh_per_m3_from_setting"] - 277.0) < 0.1
    assert audit["setting_plausible_for_uk_metric_gas"] is False
    assert audit["automatic_correction_authorised"] is False
    assert audit["conversion_validated"] is False
    assert (
        gas_calorific_value_diagnostic({"calorific_value": 40})[
            "setting_plausible_for_uk_metric_gas"
        ]
        is True
    )
    assert (
        gas_calorific_value_diagnostic({"calorific_value": True})[
            "provider_calorific_value"
        ]
        is None
    )


def test_corrected_gas_observations_retain_original_conflict_and_survive_restart():
    ledger = SupplierIntervalLedger()
    start = NOW - timedelta(days=1)
    source = "octopus_estimated_gas"
    original = {**_row(start, 184.238, "gas"), "consumption_m3": 0.665}
    revised = {**original, "kwh": round(0.665 * 1.02264 * 39.3 / 3.6, 3)}
    assert ledger.ingest([original], source=source, now=NOW)
    assert not ledger.ingest_gas_conversion(
        [original], source=source, calorific_value=975.3, now=NOW
    )
    assert ledger.ingest([revised], source=source, now=NOW)
    assert ledger.ingest_gas_conversion(
        [revised], source=source, calorific_value=39.3, now=NOW
    )
    assert not ledger.ingest_gas_conversion(
        [revised], source=source, calorific_value=39.3, now=NOW
    )
    assert ledger.ingest([_row(start, 7.42, "gas")], source="octopus_csv", now=NOW)
    report = ledger.gas_conversion_comparison()
    assert report["same_volume_changed_kwh_rows"] == 1
    assert report["nonzero_csv_overlap_rows"] == 1
    assert report["max_absolute_nonzero_csv_difference_kwh"] == round(
        abs(revised["kwh"] - 7.42), 6
    )
    assert report["recent_nonzero_rows"][0]["raw_first_seen_kwh"] == 184.238
    assert report["recent_nonzero_rows"][0]["raw_conflict_retained"] is True
    assert report["supplier_conversion_validated"] is False
    assert report["automatic_gas_financially_usable"] is False
    assert ledger.rows[("gas", start.isoformat())]["kwh"] == 7.42
    restored = SupplierIntervalLedger()
    restored.restore(ledger.dump(), now=NOW)
    assert restored.summary() == ledger.summary()


def test_gas_conversion_rejects_bad_values_and_keeps_distinct_settings():
    ledger = SupplierIntervalLedger()
    start = NOW - timedelta(days=1)
    source = "octopus_estimated_gas"
    good = {
        **_row(start, round(0.665 * 1.02264 * 39.3 / 3.6, 3), "gas"),
        "consumption_m3": 0.665,
    }
    for value in (None, True, 975.3, float("nan")):
        assert not ledger.ingest_gas_conversion(
            [good], source=source, calorific_value=value, now=NOW
        )
    for bad in (
        {**good, "kwh": 184.238},
        {**good, "consumption_m3": True},
        {**good, "consumption_m3": None},
        {**good, "consumption_m3": 0},
        _row(NOW, 7.424, "gas"),
        {**good, "kind": "electricity_import"},
    ):
        assert not ledger.ingest_gas_conversion(
            [bad], source=source, calorific_value=39.3, now=NOW
        )
    assert not ledger.ingest_gas_conversion(
        [good], source="octopus_csv", calorific_value=39.3, now=NOW
    )
    assert ledger.ingest_gas_conversion(
        [good], source=source, calorific_value=39.3, now=NOW
    )
    different_setting = {**good, "kwh": round(0.665 * 1.02264 * 40 / 3.6, 3)}
    assert ledger.ingest_gas_conversion(
        [different_setting], source=source, calorific_value=40, now=NOW
    )
    conflicting = {**good, "consumption_m3": 1.0, "kwh": 11.164}
    assert ledger.ingest_gas_conversion(
        [conflicting], source=source, calorific_value=39.3, now=NOW
    )
    report = ledger.gas_conversion_comparison()
    assert report["retained_rows"] == 2
    assert report["conflicting_rows"] == 1
    assert report["nonzero_rows"] == 1
    assert ledger.complete_day_totals("gas") == {}


def test_gas_conversion_complete_day_requires_all_intervals_same_setting():
    ledger = SupplierIntervalLedger()
    start = datetime(2026, 10, 24, 23, tzinfo=UTC)
    rows = [
        {**_row(start + timedelta(minutes=30 * n), 0, "gas"), "consumption_m3": 0}
        for n in range(50)
    ]
    source = "octopus_estimated_gas"
    assert ledger.ingest_gas_conversion(
        rows[:-1], source=source, calorific_value=39.3, now=NOW
    )
    assert ledger.ingest_gas_conversion(
        rows[-1:], source=source, calorific_value=40, now=NOW
    )
    assert not any(
        row["complete_observed_day"]
        for row in ledger.gas_conversion_comparison()["recent_days_by_setting"]
    )
    assert ledger.ingest_gas_conversion(
        rows[-1:], source=source, calorific_value=39.3, now=NOW
    )
    report = ledger.gas_conversion_comparison()
    assert report["recent_days_by_setting"][0]["complete_observed_day"] is True
    assert report["nonzero_rows"] == 0
    assert report["nonzero_csv_overlap_rows"] == 0
    assert ledger.complete_day_totals("gas") == {}



def test_provisional_gas_requires_nonzero_csv_corroboration_and_prefers_csv():
    from types import SimpleNamespace

    ledger = SupplierIntervalLedger()
    start = NOW - timedelta(days=2)
    rows = [
        {
            **_row(start + timedelta(minutes=30 * n), 11.164 if n < 4 else 0, "gas"),
            "consumption_m3": 1 if n < 4 else 0,
        }
        for n in range(96)
    ]
    # The second day has independent observed readings, not copied CSV.
    rows[48]["consumption_m3"] = 1
    rows[48]["kwh"] = 11.164
    assert ledger.ingest_gas_conversion(
        rows, source="octopus_estimated_gas", calorific_value=39.3, now=NOW
    )
    assert ledger.provisional_gas_reconciliation([], now=NOW)["provisional_days"] == 0
    csv = [{**row, "kwh": 11.192 if row["kwh"] else 0} for row in rows[:48]]
    assert ledger.ingest(csv, source="octopus_csv", now=NOW)
    record = SimpleNamespace(
        timestamp=start + timedelta(days=1),
        gas_current_rate=8.0,
        gas_standing_charge=28.0,
    )
    report = ledger.provisional_gas_reconciliation([record], now=NOW)
    assert report["csv_corroborated_settings"] == [39.3]
    assert report["provisional_days"] == 1
    assert report["recent_days"][0]["kwh"] == 44.768
    assert report["recent_days"][1]["kwh"] == 11.164
    assert report["recent_days"][1]["estimated_total_cost_pence"] == 117.312
    assert report["roi_or_ledger_write_authorised"] is False
    assert ledger.ingest([rows[48]], source="octopus_csv", now=NOW)
    report = ledger.provisional_gas_reconciliation([], now=NOW)
    assert report["recent_days"][1]["csv_intervals"] == 1
    assert report["recent_days"][1]["estimated_total_cost_pence"] is None
    assert ledger.ingest(rows[49:], source="octopus_csv", now=NOW)
    assert ledger.provisional_gas_reconciliation([], now=NOW)["provisional_days"] == 0
