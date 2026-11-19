"""Alpha9.235: bounded backlog diagnostics must not change live dispatch or money."""

from __future__ import annotations

import ast
import importlib.util
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
SPEC = importlib.util.spec_from_file_location(
    "kems_alpha9235_audit", ROOT / "kems_core" / "diagnostic_evidence.py"
)
assert SPEC is not None and SPEC.loader is not None
audit_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_module)


def _slot(start: datetime, shadow_kwh: float, *, settled: bool = True) -> dict:
    item = {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "grid_export_kwh": shadow_kwh,
        "rate_pence": 18.41,
    }
    if settled:
        item["settlement_source"] = "settled shadow digital-twin outcome"
    return item


def _observation(at: datetime, power_kw: float) -> SimpleNamespace:
    return SimpleNamespace(timestamp=at, grid_export_kw=power_kw, stale_fields=())


def _audit(now: datetime, slots: list[dict], records: list) -> dict:
    return audit_module.agile_export_interval_audit(
        now=now,
        agile_state={"today_slots": slots},
        records=records,
        reported_grid_export_kwh=9.0,
        reported_income_pence=18.41,
        activation_cutoff="2026-11-19T00:00:00+00:00",
    )


def test_ranked_variance_surfaces_cancelling_errors_without_changing_totals() -> None:
    start = datetime(2026, 11, 19, 20, tzinfo=UTC)
    slots = [
        _slot(start, 1.5),
        _slot(start + timedelta(minutes=30), 0.0),
        _slot(start + timedelta(minutes=60), 0.1),
    ]
    original = deepcopy(slots)
    records = [
        _observation(start, 2.0),
        _observation(start + timedelta(minutes=30), 2.0),
        _observation(start + timedelta(minutes=60), 0.0),
        _observation(start + timedelta(minutes=90), 0.0),
    ]
    result = _audit(start + timedelta(minutes=95), slots, records)
    assert result["status"] == "compared"
    assert result["shadow_minus_snapshot_completed_kwh"] == -0.4
    assert result["settled_variance_absolute_sum_kwh"] == 1.6
    assert result["settled_variance_positive_sum_kwh"] == 0.6
    assert result["settled_variance_negative_sum_kwh"] == -1.0
    assert result["top_settled_variance_rows_omitted"] == 0
    top = result["top_settled_variance_rows"]
    assert [r["shadow_minus_snapshot_kwh"] for r in top] == [-1.0, 0.5, 0.1]
    assert top[0]["sample_coverage_percent"] == 100.0
    assert top[0]["evidence_limitation_flags"] == []
    assert result["reporting_only"] is True
    assert "independent supplier export meter" in result["variance_triage_note"]
    assert slots == original


def test_variance_triage_marks_gaps_and_crossings_without_claiming_cause() -> None:
    start = datetime(2026, 11, 19, 20, tzinfo=UTC)
    result = _audit(
        start + timedelta(minutes=65),
        [_slot(start, 1.0), _slot(start + timedelta(minutes=30), 2.0, settled=False)],
        [
            _observation(start + timedelta(minutes=20), 2.0),
            _observation(start + timedelta(minutes=40), 0.0),
        ],
    )
    assert result["settled_shadow_slots"] == 1
    assert result["top_settled_variance_rows_omitted"] == 0
    top = result["top_settled_variance_rows"][0]
    assert top["shadow_minus_snapshot_kwh"] == 0.3333
    assert "incomplete_observation_coverage" in top["evidence_limitation_flags"]
    assert "cross_slot_sample_pair" in top["evidence_limitation_flags"]
    assert "over_ten_minute_sample_gap" in top["evidence_limitation_flags"]
    assert len(result["top_settled_variance_rows"]) == 1


def test_coordinator_restart_index_is_observability_only() -> None:
    source = (ROOT / "coordinator.py").read_text()
    module = ast.parse(source)
    cls = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "KEMSCoordinator"
    )
    update = next(
        node
        for node in cls.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_update_data"
    )
    scan_source = ast.unparse(update)
    assert "scan_index_since_setup" in scan_source
    assert "first_three_after_setup" in scan_source
    assert "_coordinator_scan_index_since_setup += 1" in scan_source
    assert "_foxess_control.async_update" in scan_source
