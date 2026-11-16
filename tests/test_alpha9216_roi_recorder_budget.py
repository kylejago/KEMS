"""Recorder attribute-budget regression without rewriting KEMS reward history."""

import importlib.util
import json
from pathlib import Path

SRC = (
    Path(__file__).resolve().parents[1]
    / "custom_components/kems/kems_core/roi_reward_sensor_attributes.py"
)
SPEC = importlib.util.spec_from_file_location("alpha9216_reward_attributes", SRC)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_large_reward_ledger_stays_under_recorder_limit():
    rows = [
        {
            "event_id": f"power-down-{i}",
            "event_status": "estimated_not_supplier_confirmed",
            "provenance": "x" * 4000,
        }
        for i in range(128)
    ]
    original = list(rows)
    audit = {
        "schema_version": 1,
        "included_total_pence": 12345.67,
        "unsettled_total_pence": 12345.67,
        "supplier_settlement_available": False,
        "historical_coverage": {"note": "y" * 7000},
        "entries": rows,
    }
    compact = mod.compact_roi_reward_audit(audit)
    actual_bytes = len(
        json.dumps(compact, ensure_ascii=False, default=str).encode("utf-8")
    )
    assert actual_bytes < 16_384
    assert compact["included_total_pence"] == 12345.67
    assert compact["supplier_settlement_available"] is False
    assert compact["sensor_entries_truncated"] is True
    assert compact["entries_omitted"] >= 120
    assert len(rows) == 128
    assert rows == original
    assert compact["full_entries_in_diagnostics"] is True
