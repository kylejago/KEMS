"""Read-only evidence tests for Agile half-hour export reconciliation."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

MODULE = (
    Path(__file__).parents[1]
    / "custom_components"
    / "kems"
    / "kems_core"
    / "diagnostic_evidence.py"
)
SPEC = importlib.util.spec_from_file_location("kems_alpha9194_diagnostic_evidence", MODULE)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def _record(time: datetime, kw: float, *, stale: bool = False):
    return SimpleNamespace(
        timestamp=time,
        grid_export_kw=kw,
        stale_fields=("grid_export_kw",) if stale else (),
    )


def _slot(start: datetime, rate: float | None, model_kwh: float) -> dict:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "rate_pence": rate,
        "grid_export_kwh": model_kwh,
        "settlement_source": "settled shadow digital-twin outcome",
    }


def _run(state, records, *, now=None, cutoff=None, observed_kwh=0.9, income=24.11):
    return helper.agile_export_interval_audit(
        records=records,
        agile_state=state,
        now=now or datetime(2026, 11, 10, 20, 45, tzinfo=UTC),
        reported_grid_export_kwh=observed_kwh,
        reported_income_pence=income,
        activation_cutoff=cutoff or "2026-11-10T00:00:00+00:00",
    )


def test_completed_shadow_vs_snapshot_samples_stays_separate_and_read_only() -> None:
    start = datetime(2026, 11, 10, 20, tzinfo=UTC)
    state = {"today_slots": [_slot(start, 24.11, 1.25), _slot(start + timedelta(minutes=30), 20.0, 0.0)]}
    original = deepcopy(state)
    records = [
        _record(start, 2.0),
        _record(start + timedelta(minutes=5), 2.0),
        _record(start + timedelta(minutes=10), 2.0),
        _record(start + timedelta(minutes=30), 0.0),
        _record(start + timedelta(minutes=35), 0.0),
    ]
    audit = _run(state, records)
    assert audit["status"] == "compared"
    assert audit["snapshot_integrated_export_all_elapsed_kwh"] == 1.0
    assert audit["snapshot_integrated_export_completed_slots_kwh"] == 1.0
    assert audit["shadow_completed_grid_export_kwh"] == 1.25
    assert audit["shadow_minus_snapshot_completed_kwh"] == 0.25
    assert audit["sample_priced_income_pence"] == 24.11
    assert audit["sample_income_minus_reported_pence"] == 0.0
    assert audit["reported_daily_simulation_export_kwh"] == 0.9
    assert audit["reporting_only"] is True
    assert state == original


def test_current_partial_slot_is_included_in_actual_income_not_completed_shadow() -> None:
    start = datetime(2026, 11, 10, 20, tzinfo=UTC)
    state = {"today_slots": [_slot(start, 10.0, 0.5), _slot(start + timedelta(minutes=30), 20.0, 9.0)]}
    records = [
        _record(start, 1.0),
        _record(start + timedelta(minutes=30), 2.0),
        _record(start + timedelta(minutes=40), 0.0),
    ]
    audit = _run(state, records, income=8.33)
    assert audit["completed_slots"] == 1
    assert audit["snapshot_integrated_export_all_elapsed_kwh"] == 0.833
    assert audit["snapshot_integrated_export_completed_slots_kwh"] == 0.5
    assert audit["shadow_completed_grid_export_kwh"] == 0.5
    assert audit["sample_priced_income_pence"] == 11.67
    assert audit["rows"][1]["shadow_grid_export_kwh"] is None


def test_missing_price_does_not_invent_income() -> None:
    start = datetime(2026, 11, 10, 20, tzinfo=UTC)
    state = {"today_slots": [_slot(start, None, 1.0)]}
    records = [_record(start, 2.0), _record(start + timedelta(minutes=30), 0.0)]
    audit = _run(state, records)
    assert audit["status"] == "incomplete_price_or_slot_coverage"
    assert audit["unpriced_positive_sample_pairs"] == 1
    assert audit["sample_priced_income_pence"] is None
    assert audit["rows"][0]["snapshot_integrated_export_kwh"] == 1.0


def test_activation_cutoff_is_fail_closed() -> None:
    start = datetime(2026, 11, 10, 20, tzinfo=UTC)
    state = {"today_slots": [_slot(start, 20.0, 1.0)]}
    records = [
        _record(start, 2.0),
        _record(start + timedelta(minutes=5), 4.0),
        _record(start + timedelta(minutes=30), 0.0),
    ]
    audit = _run(state, records, cutoff="2026-11-10T20:05:00+00:00")
    assert audit["sample_priced_income_pence"] == 33.33
    assert audit["snapshot_integrated_export_all_elapsed_kwh"] == 1.667
    denied = helper.agile_export_interval_audit(
        records=records,
        agile_state=state,
        now=datetime(2026, 11, 10, 20, 45, tzinfo=UTC),
        reported_grid_export_kwh=1.0,
        reported_income_pence=20.0,
        activation_cutoff=None,
    )
    assert denied["status"] == "paid_export_activation_unverified"


def test_long_gap_and_boundary_crossing_are_explicit_not_verified() -> None:
    start = datetime(2026, 11, 10, 20, tzinfo=UTC)
    state = {"today_slots": [_slot(start, 12.0, 0.5), _slot(start + timedelta(minutes=30), 14.0, 0.5)]}
    records = [
        _record(start + timedelta(minutes=25), 2.0),
        _record(start + timedelta(minutes=40), 0.0),
    ]
    audit = _run(state, records)
    assert audit["long_gap_pairs"] == 1
    assert audit["boundary_crossing_pairs"] == 1
    assert audit["snapshot_integrated_export_all_elapsed_kwh"] == 0.5
    assert audit["sample_priced_income_pence"] == 6.0


def test_dst_fallback_intervals_keep_distinct_offsets() -> None:
    from zoneinfo import ZoneInfo

    london = ZoneInfo("Europe/London")
    start_a = datetime(2026, 10, 25, 0, tzinfo=UTC)
    start_b = datetime(2026, 10, 25, 1, tzinfo=UTC)
    state = {"today_slots": [_slot(start_a, 10.0, 1.0), _slot(start_b, 20.0, 2.0)]}
    records = [
        _record(start_a, 2.0),
        _record(start_a + timedelta(minutes=30), 0.0),
        _record(start_b, 2.0),
        _record(start_b + timedelta(minutes=30), 0.0),
    ]
    audit = _run(state, records, now=datetime(2026, 10, 25, 2, tzinfo=UTC), cutoff="2026-10-25T00:00:00+00:00")
    assert start_a.astimezone(london).hour == start_b.astimezone(london).hour == 1
    assert audit["completed_slots"] == 2
    assert audit["sample_priced_income_pence"] == 30.0
