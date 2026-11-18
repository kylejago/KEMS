"""Reporting-only historical completeness evidence; no invented meter samples."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

from kems_core.periods import recorded_totals_present

FILE = (
    Path(__file__).resolve().parents[1] / "custom_components" / "kems" / "lifetime.py"
)
SOURCE = FILE.read_text()
TREE = ast.parse(SOURCE)
OWNER = next(
    node
    for node in TREE.body
    if isinstance(node, ast.ClassDef) and node.name == "LifetimeLedgerRecorder"
)


def _method(name: str):
    node = next(
        node
        for node in OWNER.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )
    klass = ast.ClassDef(
        name="Recorder",
        bases=[],
        keywords=[],
        body=[node],
        decorator_list=[],
    )
    namespace = {
        "PERIOD_DATA_COMPLETE_KEY": "__data_complete",
        "recorded_totals_present": recorded_totals_present,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[klass], type_ignores=[])),
            "<history-audit>",
            "exec",
        ),
        namespace,
    )
    return namespace["Recorder"]


def test_coverage_audit_records_real_reason_without_reclassifying_days():
    cls = _method("historical_coverage_audit")
    recorder = cls()
    recorder._daily_records = {
        "2026-11-14": {"__data_complete": 1.0},
        "2026-11-15": {
            "__data_complete": 0.0,
            "__data_coverage_percent": 98.4,
            "grid_import_kwh": 84.5,
        },
    }
    recorder._tracking_date = date(2026, 11, 16)
    recorder._tracking_values = {
        "__data_complete": 0.0,
        "__data_coverage_percent": 60.0,
    }
    result = recorder.historical_coverage_audit
    assert result["required_simulation_coverage_percent"] == 99.9
    assert result["recorded_days"] == 3
    assert result["incomplete_recorded_days"] == 2
    assert result["simulation_replay_incomplete_days"] == 2
    assert result["days_with_recorded_totals"] == 1
    assert result["independent_meter_complete_days_verified"] == 0
    assert result["recorded_totals_do_not_prove_meter_completeness"] is True
    assert result["recent_days"][0]["simulation_data_coverage_percent"] is None
    assert result["recent_days"][1]["simulation_data_coverage_percent"] == 98.4
    assert result["recent_days"][2]["data_complete"] is False
    assert recorder._daily_records["2026-11-15"]["__data_complete"] == 0.0
    assert result["no_missing_samples_inferred"] is True


def test_coverage_audit_bounded_and_old_days_explicitly_unknown():
    cls = _method("historical_coverage_audit")
    recorder = cls()
    recorder._daily_records = {
        f"2026-10-{i:02d}": {"grid_import_kwh": float(i)} for i in range(1, 32)
    }
    recorder._tracking_date = None
    recorder._tracking_values = {}
    result = recorder.historical_coverage_audit
    assert result["recorded_days"] == 31
    assert len(result["recent_days"]) == 14
    assert result["older_coverage_percent_unavailable"]
    assert all(
        row["simulation_data_coverage_percent"] is None for row in result["recent_days"]
    )


def test_coverage_metadata_not_used_as_energy_or_money_delta():
    assert 'if key in (PERIOD_DATA_COMPLETE_KEY, "__data_coverage_percent"):' in SOURCE
    assert '"__data_coverage_percent": float(simulation.data_coverage)' in SOURCE
    assert '"historical_coverage_audit"' in (FILE.parent / "diagnostics.py").read_text()
