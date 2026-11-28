"""Supplier charges and completed-event evidence are independent of live control."""

from datetime import UTC, datetime, timedelta

from kems_core.models import LifetimeLedger, PeriodTotals
from kems_core.supplier_charges import (
    SupplierChargeEvidence,
    baseline_capture_diagnostic,
    capture_completed_baseline,
    capture_joined_baseline,
    completed_power_down_estimate,
    historical_charge_adjustment_preview,
    historical_reporting_what_if,
    merge_completed_baseline,
    project_reviewed_historical_charges,
    supplier_cost_rows,
)
from kems_core.supplier_intervals import SupplierIntervalLedger

NOW = datetime(2026, 11, 27, tzinfo=UTC)
START = NOW - timedelta(days=2)


def _row(start, kind="electricity_import", kwh=1.0, charge=6.6):
    return {
        "kind": kind,
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=30)).isoformat(),
        "kwh": kwh,
        "charge_pence": charge,
    }


def _day(start, kind="electricity_import", count=48):
    return [_row(start + timedelta(minutes=30 * n), kind) for n in range(count)]


def _compare(charges, energy, commission="2026-11-24"):
    return charges.reconciliation(
        energy,
        {"2026-11-25": {"import_cost_pence": 300.0}},
        now=NOW,
        commissioning_date=commission,
    )


def test_matched_complete_priced_day_is_read_only_and_restart_safe():
    energy = SupplierIntervalLedger()
    charges = SupplierChargeEvidence()
    rows = _day(START)
    energy.ingest(rows, source="octopus_csv", now=NOW)
    assert charges.ingest(rows, source="octopus_csv", now=NOW)
    assert not charges.ingest(rows, source="octopus_csv", now=NOW)
    before = energy.dump()
    result = _compare(charges, energy)
    data = result["kinds"]["electricity_import"]
    assert data["complete_priced_post_commissioning_days"] == 1
    assert data["complete_energy_post_commissioning_days"] == 1
    assert data["complete_energy_days_missing_valid_prices"] == 0
    assert data["difference_pence"] == 16.8
    assert result["roi_or_ledger_write_authorised"] is False
    assert result["standing_charges_and_event_rewards_excluded"] is True
    assert energy.dump() == before
    restored = SupplierChargeEvidence()
    restored.restore(charges.dump(), now=NOW)
    assert _compare(restored, energy) == result
    assert (
        _compare(charges, energy, commission="2026-11-25")["kinds"][
            "electricity_import"
        ]["complete_priced_post_commissioning_days"]
        == 0
    )
    assert (
        _compare(charges, energy, commission=None)["kinds"]["electricity_import"][
            "complete_priced_post_commissioning_days"
        ]
        == 0
    )


def test_missing_energy_or_pricing_and_conflict_withhold_day():
    energy = SupplierIntervalLedger()
    charges = SupplierChargeEvidence()
    rows = _day(START)
    energy.ingest(rows[:-1], source="octopus_csv", now=NOW)
    charges.ingest(rows, source="octopus_csv", now=NOW)
    assert (
        _compare(charges, energy)["kinds"]["electricity_import"][
            "complete_priced_post_commissioning_days"
        ]
        == 0
    )
    energy.ingest(rows[-1:], source="octopus_csv", now=NOW)
    charges.ingest(
        [{**rows[0], "charge_pence": 7.6}], source="octopus_integration", now=NOW
    )
    assert _compare(charges, energy)["unmatched_or_conflicted_intervals"] == 1
    assert (
        _compare(charges, energy)["kinds"]["electricity_import"][
            "complete_priced_post_commissioning_days"
        ]
        == 0
    )


def test_late_baseline_survives_until_both_meter_windows_are_available():
    end = START + timedelta(hours=1)
    event = {
        "available": True,
        "session_id": "test",
        "session_start": START.isoformat(),
        "session_end": end.isoformat(),
    }
    baseline = {
        "baselines": [
            {
                "start": (START + timedelta(minutes=30 * n)).isoformat(),
                "end": (START + timedelta(minutes=30 * (n + 1))).isoformat(),
                "baseline": 0.5,
                "is_incomplete_calculation": False,
            }
            for n in range(2)
        ],
        "total_baseline": 1.0,
    }
    captured = capture_completed_baseline(
        event, baseline, baseline, now=NOW, points_per_kwh=800
    )
    assert captured is not None
    partial = capture_completed_baseline(
        event, baseline, {}, now=NOW, allow_partial=True
    )
    other = capture_completed_baseline(
        event, {}, baseline, now=NOW, points_per_kwh=800, allow_partial=True
    )
    assert partial is not None and other is not None
    assert merge_completed_baseline(partial, other) == captured
    conflicting = {**other, "export_baseline_kwh": 2.0}
    assert merge_completed_baseline(captured, conflicting)["conflict"]
    energy = SupplierIntervalLedger()
    assert (
        completed_power_down_estimate(energy, partial)["status"]
        == "awaiting_exact_baseline_evidence"
    )
    assert (
        completed_power_down_estimate(energy, captured)["estimated_bonus_pence"] is None
    )
    imports = [
        _row(START + timedelta(minutes=30 * n), kwh=0.0, charge=0.0) for n in range(2)
    ]
    exports = [
        _row(START + timedelta(minutes=30 * n), "electricity_export", 2.0)
        for n in range(2)
    ]
    energy.ingest(imports, source="octopus_csv", now=NOW)
    assert (
        completed_power_down_estimate(energy, captured)["estimated_bonus_pence"] is None
    )
    energy.ingest(exports, source="octopus_csv", now=NOW)
    estimate = completed_power_down_estimate(energy, captured)
    assert estimate["estimated_bonus_pence"] == 400.0
    assert estimate["supplier_settled"] is False
    assert estimate["roi_or_ledger_write_authorised"] is False
    assert (
        completed_power_down_estimate(energy, {**captured, "octopoints_per_kwh": None})[
            "estimated_bonus_pence"
        ]
        is None
    )
    energy.ingest([{**exports[0], "kwh": 3.0}], source="octopus_csv", now=NOW)
    assert (
        completed_power_down_estimate(energy, captured)["estimated_bonus_pence"] is None
    )
    assert capture_completed_baseline(event, baseline, {}, now=NOW) is None
    assert (
        capture_completed_baseline(
            event,
            baseline,
            {**baseline, "baselines": baseline["baselines"][:1]},
            now=NOW,
        )
        is None
    )


def test_joined_baseline_capture_before_event_completion():
    start = NOW + timedelta(hours=1)
    end = start + timedelta(hours=1)
    event = {
        "id": "future",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "octopoints_per_kwh": 80,
    }
    baseline = {
        "baselines": [
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "baseline": 0.4,
                "is_incomplete_calculation": False,
            }
        ]
    }
    evidence = capture_joined_baseline(event, baseline, {}, now=NOW)
    assert evidence is not None
    assert evidence["import_baseline_kwh"] == 0.4
    assert evidence["export_baseline_kwh"] is None
    assert capture_joined_baseline(event, {}, {}, now=NOW) is None
    assert capture_joined_baseline(event, baseline, {}, now=START) is None
    assert capture_joined_baseline(event, baseline, {}, now=end) == evidence


def test_joined_baseline_merges_only_exact_nonconflicting_half_hours():
    start = NOW + timedelta(hours=1)
    middle = start + timedelta(minutes=30)
    end = start + timedelta(hours=1)
    event = {
        "id": "split",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "octopoints_per_kwh": 136,
    }

    def attrs(left, right, value, incomplete=False):
        return {
            "baselines": [
                {
                    "start": left.isoformat(),
                    "end": right.isoformat(),
                    "baseline": value,
                    "is_incomplete_calculation": incomplete,
                }
            ],
            "total_baseline": value,
        }

    first = attrs(start, middle, 0.25)
    second = attrs(middle, end, 0.5)
    early = capture_joined_baseline(event, first, first, now=NOW)
    late = capture_joined_baseline(event, second, second, now=middle)
    assert early["import_baseline_kwh"] is None
    assert early["import_baseline_rows"] == {start.isoformat(): 0.25}
    assert late["export_baseline_kwh"] is None
    merged = merge_completed_baseline(early, late)
    assert merged["import_baseline_kwh"] == 0.75
    assert merged["export_baseline_kwh"] == 0.75
    assert merge_completed_baseline(merged, late) == merged
    revised = capture_joined_baseline(event, attrs(start, middle, 0.3), {}, now=NOW)
    assert merge_completed_baseline(merged, revised)["conflict"] is True
    assert (
        capture_joined_baseline(
            event, attrs(start, middle, 0.25, incomplete=True), {}, now=NOW
        )
        is None
    )
    assert (
        capture_joined_baseline(event, attrs(START, middle, 0.25), {}, now=NOW) is None
    )


def test_recorded_cost_rows_require_explicit_direction_unit_and_raw_cost():
    attrs = {
        "unit_of_measurement": "GBP",
        "is_export": False,
        "charges": [
            {
                "start": START.isoformat(),
                "end": (START + timedelta(minutes=30)).isoformat(),
                "consumption": 1.0,
                "raw_cost": 0.066,
            }
        ],
    }
    rows = supplier_cost_rows("electricity_import", attrs)
    assert len(rows) == 1
    assert abs(rows[0]["charge_pence"] - 6.6) < 0.000001
    assert not supplier_cost_rows("electricity_export", attrs)
    assert not supplier_cost_rows("electricity_import", {**attrs, "charges": []})
    assert not supplier_cost_rows(
        "electricity_import", {**attrs, "unit_of_measurement": "p"}
    )


def test_joined_identity_survives_missing_or_incomplete_baseline():
    start = NOW + timedelta(hours=1)
    end = start + timedelta(hours=1)
    event = {
        "id": "future",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "octopoints_per_kwh": 136,
    }
    attrs = {
        "baselines": [
            {
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=30)).isoformat(),
                "baseline": 0.4,
                "is_incomplete_calculation": True,
            }
        ],
    }
    retained = capture_joined_baseline(
        event, attrs, {}, now=NOW, retain_event_identity=True
    )
    assert retained["octopoints_per_kwh"] == 136
    assert retained["import_baseline_kwh"] is None
    assert retained["import_baseline_rows"] == {}
    audit = baseline_capture_diagnostic(attrs, start, end)
    assert audit["rows_explicitly_incomplete"] == 1
    assert audit["accepted_half_hours"] == 0
    assert audit["exact_total_available"] is False


def test_historical_baseline_recovery_requires_exact_complete_rows():
    from kems_core.supplier_charges import recover_historical_baselines

    start = datetime(2026, 11, 25, 16, tzinfo=UTC)
    end = start + timedelta(hours=1)
    event = {
        "session_id": "known",
        "session_start": start.isoformat(),
        "session_end": end.isoformat(),
    }
    attrs = {
        "baselines": [
            {
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=30)).isoformat(),
                "baseline": 0.5,
                "is_incomplete_calculation": False,
            }
        ]
    }
    result = recover_historical_baselines([event], attrs, "import")
    assert result[0]["import_baseline_rows"] == {start.isoformat(): 0.5}
    assert result[0]["import_baseline_kwh"] is None
    assert result[0]["export_baseline_rows"] == {}
    attrs["baselines"][0]["is_incomplete_calculation"] = True
    assert not recover_historical_baselines([event], attrs, "import")
    assert not recover_historical_baselines([], attrs, "import")


def test_power_down_reward_is_clipped_per_half_hour():
    end = START + timedelta(hours=1)
    baseline = {
        "session_id": "test",
        "session_start": START.isoformat(),
        "session_end": end.isoformat(),
        "import_baseline_kwh": 1.0,
        "export_baseline_kwh": 1.0,
        "octopoints_per_kwh": 800,
        "import_baseline_rows": {
            (START + timedelta(minutes=30 * n)).isoformat(): 0.5 for n in range(2)
        },
        "export_baseline_rows": {
            (START + timedelta(minutes=30 * n)).isoformat(): 0.5 for n in range(2)
        },
    }
    energy = SupplierIntervalLedger()
    energy.ingest(
        [
            _row(START, kwh=2.0),
            _row(START + timedelta(minutes=30), kwh=0.0),
            _row(START, "electricity_export", 0.0),
            _row(START + timedelta(minutes=30), "electricity_export", 2.0),
        ],
        source="octopus_csv",
        now=NOW,
    )
    result = completed_power_down_estimate(energy, baseline)
    assert result["estimated_rewardable_reduction_kwh"] == 2.0
    assert result["estimated_bonus_pence"] == 200.0
    assert result["supplier_settled"] is False


def test_full_dated_adjustment_preview_preserves_originals_and_separate_rewards():
    energy = SupplierIntervalLedger()
    charges = SupplierChargeEvidence()
    rows = _day(START) + _day(START, kind="electricity_export")
    energy.ingest(rows, source="octopus_csv", now=NOW)
    charges.ingest(rows, source="octopus_csv", now=NOW)
    native = {
        "2026-11-25": {
            "import_cost_pence": 300.0,
            "export_income_pence": 320.0,
            "happy_hour_estimated_credit_pence": 70.0,
        }
    }
    audit = charges.reconciliation(
        energy,
        native,
        now=NOW,
        commissioning_date="2026-11-24",
        include_daily_audit=True,
    )
    preview = historical_charge_adjustment_preview(audit)
    assert preview["import_delta_pence"] == 16.8
    assert preview["export_delta_pence"] == -3.2
    assert preview["proposed_actual_value_delta_pence"] == -20.0
    assert preview["roi_or_ledger_write_authorised"] is False
    assert native["2026-11-25"]["import_cost_pence"] == 300.0
    assert native["2026-11-25"]["happy_hour_estimated_credit_pence"] == 70.0
    assert historical_charge_adjustment_preview(audit) == preview


def test_full_dated_adjustment_preview_excludes_missing_native_cost():
    energy = SupplierIntervalLedger()
    charges = SupplierChargeEvidence()
    rows = _day(START)
    energy.ingest(rows, source="octopus_csv", now=NOW)
    charges.ingest(rows, source="octopus_csv", now=NOW)
    audit = charges.reconciliation(
        energy,
        {},
        now=NOW,
        commissioning_date="2026-11-24",
        include_daily_audit=True,
    )
    assert historical_charge_adjustment_preview(audit)["days"] == {}


def test_reviewed_charge_projection_preserves_native_and_reward_rows():
    day = "2026-11-25"
    native = {
        day: {
            "import_cost_pence": 300.0,
            "export_income_pence": 320.0,
            "actual_avoided_import_value_pence": 100.0,
            "actual_system_value_pence": 420.0,
            "simulated_import_cost_pence": 200.0,
            "happy_hour_estimated_credit_pence": 70.0,
        }
    }
    preview = {
        "days": {
            day: {
                "import_cost_pence": {
                    "recorded_pence": 300.0,
                    "supplier_estimate_pence": 316.8,
                },
                "export_income_pence": {
                    "recorded_pence": 320.0,
                    "supplier_estimate_pence": 316.8,
                },
            }
        }
    }
    copy, audit = project_reviewed_historical_charges(native, preview)
    assert copy == native
    assert not audit["applied"]
    assert audit["withheld"][day]["import_cost_pence"] == "charge_basis_not_reviewed"
    copy, audit = project_reviewed_historical_charges(
        native, preview, reviewed_export_charges={day: (320.0, 316.8)}
    )
    assert copy[day]["import_cost_pence"] == 300.0
    assert copy[day]["actual_system_value_pence"] == 416.8
    reviewed = dict(
        reviewed_import_charges={day: (300.0, 316.8)},
        reviewed_export_charges={day: (320.0, 316.8)},
    )
    copy, audit = project_reviewed_historical_charges(native, preview, **reviewed)
    assert copy[day]["actual_avoided_import_value_pence"] == 83.2
    assert copy[day]["actual_system_value_pence"] == 400.0
    assert copy[day]["happy_hour_estimated_credit_pence"] == 70.0
    assert copy[day]["simulated_import_cost_pence"] == 200.0
    assert native[day]["actual_system_value_pence"] == 420.0
    assert audit["ledger_write_authorised"] is False
    assert project_reviewed_historical_charges(native, preview, **reviewed) == (
        copy,
        audit,
    )
    changed_preview = {
        "days": {
            day: {
                "import_cost_pence": {
                    "recorded_pence": 300.0,
                    "supplier_estimate_pence": 317.0,
                }
            }
        }
    }
    unchanged, stale_audit = project_reviewed_historical_charges(
        native, changed_preview, **reviewed
    )
    assert unchanged == native
    assert stale_audit["withheld"][day]["import_cost_pence"] == (
        "charge_pair_changed_since_review"
    )
    repeated, audit = project_reviewed_historical_charges(copy, preview, **reviewed)
    assert repeated == copy
    assert not audit["applied"]
    assert audit["withheld"][day]["import_cost_pence"] == (
        "native_charge_changed_since_review"
    )


def test_reviewed_projection_withholds_missing_commissioned_value():
    day = "2026-11-25"
    native = {day: {"import_cost_pence": 100.0}}
    preview = {
        "days": {
            day: {
                "import_cost_pence": {
                    "recorded_pence": 100.0,
                    "supplier_estimate_pence": 110.0,
                }
            }
        }
    }
    copy, audit = project_reviewed_historical_charges(
        native, preview, reviewed_import_charges={day: (100.0, 110.0)}
    )
    assert copy == native
    assert audit["withheld"][day]["import_cost_pence"] == (
        "commissioned_roi_values_missing"
    )


def test_hypothetical_reporting_uses_same_delta_for_roi_bill_and_periods():
    day = "2026-11-25"
    native = {
        day: {
            "import_cost_pence": 300.0,
            "export_income_pence": 320.0,
            "actual_avoided_import_value_pence": 100.0,
            "actual_system_value_pence": 420.0,
            "happy_hour_estimated_credit_pence": 70.0,
        }
    }
    preview = {
        "days": {
            day: {
                "import_cost_pence": {
                    "recorded_pence": 300.0,
                    "supplier_estimate_pence": 316.8,
                },
                "export_income_pence": {
                    "recorded_pence": 320.0,
                    "supplier_estimate_pence": 316.8,
                },
            }
        }
    }
    lifetime = LifetimeLedger(
        import_cost_pence=1000.0,
        export_income_pence=800.0,
        actual_avoided_import_value_pence=200.0,
        actual_system_value_pence=1000.0,
        simulated_import_cost_pence=2000.0,
    )
    periods = {
        "month": PeriodTotals(
            start_date=START.date().replace(day=1),
            end_date=NOW.date(),
            import_cost_pence=1000.0,
            export_income_pence=800.0,
            actual_avoided_import_value_pence=200.0,
            actual_system_value_pence=1000.0,
            happy_hour_estimated_credit_pence=70.0,
            simulated_import_cost_pence=2000.0,
        ),
        "today": PeriodTotals(start_date=NOW.date(), end_date=NOW.date()),
    }
    result = historical_reporting_what_if(native, preview, lifetime, periods)
    assert result["live_reporting_authorised"] is False
    assert result["reward_overlap_resolved"] is False
    assert result["hypothetical_lifetime"]["actual_system_value_pence"] == 980.0
    month = result["hypothetical_periods"]["month"]
    assert month["actual_system_value_pence"] == 980.0
    assert month["actual_net_after_estimated_happy_hour_credit_pence"] == 150.0
    assert month["happy_hour_estimated_credit_pence"] == 70.0
    assert month["simulated_import_cost_pence"] == 2000.0
    assert result["hypothetical_periods"]["today"] == periods["today"].to_dict()
    assert lifetime.actual_system_value_pence == 1000.0
    assert native[day]["import_cost_pence"] == 300.0
    assert historical_reporting_what_if(native, preview, lifetime, periods) == result
