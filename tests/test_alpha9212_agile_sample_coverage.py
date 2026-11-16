"""Alpha9.212 sample-time coverage must not be mistaken for positive export."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "kems"
    / "kems_core"
    / "diagnostic_evidence.py"
)
SPEC = importlib.util.spec_from_file_location("alpha9212_coverage", SOURCE)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def _slot(start: datetime) -> dict:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "rate_pence": 25.0,
        "grid_export_kwh": 2.0,
        "settlement_source": "settled shadow digital-twin outcome",
    }


def _record(at: datetime, power: float, stale: bool = False):
    return SimpleNamespace(
        timestamp=at,
        grid_export_kw=power,
        stale_fields=("grid_export_kw",) if stale else (),
    )


def _run(records, now):
    start = datetime(2026, 11, 16, 18, tzinfo=UTC)
    return audit.agile_export_interval_audit(
        records=records,
        agile_state={"today_slots": [_slot(start)]},
        now=now,
        reported_grid_export_kwh=0.0,
        reported_income_pence=0.0,
        activation_cutoff=start.isoformat(),
    )


def test_valid_zero_export_samples_count_as_coverage() -> None:
    start = datetime(2026, 11, 16, 18, tzinfo=UTC)
    result = _run(
        [
            _record(start, 2.0),
            _record(start + timedelta(minutes=10), 0.0),
            _record(start + timedelta(minutes=20), 0.0),
            _record(start + timedelta(minutes=30), 0.0),
        ],
        start + timedelta(minutes=31),
    )
    row = result["rows"][0]
    assert row["sample_spanned_seconds"] == 600.0
    assert row["sample_observed_seconds"] == 1800.0
    assert row["sample_coverage_percent"] == 100.0
    assert row["sample_coverage_status"] == "observed_at_least_95_percent"
    assert result["settled_slots_with_incomplete_sample_coverage"] == 0


def test_sparse_positive_pairs_do_not_claim_full_interval() -> None:
    start = datetime(2026, 11, 16, 18, tzinfo=UTC)
    result = _run(
        [
            _record(start + timedelta(minutes=3), 4.0),
            _record(start + timedelta(minutes=9), 0.0),
            _record(start + timedelta(minutes=19), 3.0, stale=True),
            _record(start + timedelta(minutes=24), 0.0),
        ],
        start + timedelta(minutes=31),
    )
    row = result["rows"][0]
    assert row["sample_observed_seconds"] == 960.0
    assert row["unobserved_seconds"] == 840.0
    assert row["sample_coverage_percent"] == 53.3
    assert row["sample_coverage_status"] == "incomplete_sample_coverage"
    assert result["settled_slots_with_incomplete_sample_coverage"] == 1
    assert result["long_gap_pairs"] == 0


def test_positive_sample_at_boundary_is_split_for_coverage_only() -> None:
    start = datetime(2026, 11, 16, 18, tzinfo=UTC)
    record = [_record(start + timedelta(minutes=25), 6.0),
              _record(start + timedelta(minutes=35), 0.0)]
    result = _run(record, start + timedelta(minutes=40))
    row = result["rows"][0]
    assert row["sample_observed_seconds"] == 300.0
    assert row["sample_coverage_percent"] == 16.7
    assert row["sample_coverage_status"] == "incomplete_sample_coverage"
    assert result["sample_priced_income_pence"] == 25.0
