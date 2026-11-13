"""ROI audit entity attributes remain Recorder-safe without losing ledger totals."""

from __future__ import annotations

import json
from copy import deepcopy

from kems_core.roi_reward_sensor_attributes import (
    MAX_SENSOR_ATTRIBUTES_BYTES,
    MAX_SENSOR_ENTRIES,
    compact_roi_reward_audit,
)


def _audit(count: int, *, huge: bool = False) -> dict:
    return {
        "schema_version": 2,
        "reporting_only": True,
        "historical_coverage": {
            "commissioning_date": "2026-09-12",
            "known_power_down_events": count,
            "note": "witnessed events only",
        },
        "supplier_settled_pence": 30.0,
        "included_total_pence": 926.349057,
        "included_happy_hour_pence": 896.349057,
        "included_power_down_pence": 30.0,
        "included_count": 10,
        "pending_count": count - 10,
        "entries": [
            {
                "type": "power_down",
                "event_id": str(index),
                "reward_key": str(index),
                "estimated_reward_pence": None,
                "supplier_settled": False,
                "status": "pending_bonus_or_baseline_evidence",
                "evidence_source": "real_meter" + ("X" * 20_000 if huge else ""),
            }
            for index in range(count)
        ],
        "entries_omitted": 0,
        "note": "No fabricated supplier reward or export earnings.",
    }


def _byte_count(attrs: dict) -> int:
    return len(
        json.dumps(attrs, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )


def test_many_events_keep_exact_financial_summary_and_bound_recorder_attributes():
    original = _audit(200)
    saved = deepcopy(original)
    result = compact_roi_reward_audit(original)
    assert original == saved
    assert result["included_total_pence"] == original["included_total_pence"]
    assert result["supplier_settled_pence"] == original["supplier_settled_pence"]
    assert result["included_count"] == original["included_count"]
    assert result["pending_count"] == original["pending_count"]
    assert len(result["entries"]) <= MAX_SENSOR_ENTRIES
    assert result["entries_omitted"] == 200 - len(result["entries"])
    assert result["sensor_entries_truncated"] is True
    assert result["full_entries_in_diagnostics"] is True
    assert _byte_count(result) < MAX_SENSOR_ATTRIBUTES_BYTES


def test_large_event_row_is_omitted_without_losing_financial_status():
    result = compact_roi_reward_audit(_audit(20, huge=True))
    assert result["entries"] == []
    assert result["entries_omitted"] == 20
    assert result["supplier_settled_pence"] == 30.0
    assert result["included_happy_hour_pence"] == 896.349057
    assert _byte_count(result) < MAX_SENSOR_ATTRIBUTES_BYTES


def test_small_audit_keeps_all_event_fields_without_truncation():
    original = _audit(2)
    result = compact_roi_reward_audit(original)
    assert result["entries"] == original["entries"]
    assert result["entries_omitted"] == 0
    assert result["sensor_entries_truncated"] is False


def test_previously_omitted_rows_remain_accounted_for():
    audit = _audit(5)
    audit["entries_omitted"] = 12
    result = compact_roi_reward_audit(audit)
    assert result["entries_omitted"] == 12
    assert result["sensor_entries_truncated"] is True


def test_oversized_notes_stay_bounded_and_financial_totals_unchanged():
    audit = _audit(1)
    audit["note"] = "N" * 100_000
    audit["historical_coverage"]["note"] = "C" * 100_000
    result = compact_roi_reward_audit(audit)
    assert _byte_count(result) < MAX_SENSOR_ATTRIBUTES_BYTES
    assert result["included_total_pence"] == audit["included_total_pence"]
