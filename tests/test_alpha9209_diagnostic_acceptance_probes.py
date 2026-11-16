"""Alpha9.209 evidence probes never change hardware or fabricate supplier data."""

from __future__ import annotations

from types import SimpleNamespace

from kems_core.operational_diagnostic_probes import (
    RECORDER_LIMIT_BYTES,
    power_down_baseline_probe,
    roi_recorder_probe,
)
from kems_core.roi_reward_sensor_attributes import compact_roi_reward_audit


def _audit() -> dict:
    return {
        "included_count": 13,
        "pending_count": 15,
        "included_total_pence": 1452.396728,
        "included_happy_hour_pence": 1370.396728,
        "included_power_down_pence": 82.0,
        "entries": [
            {"event_id": str(i), "status": "pending_evidence", "note": "X" * 150}
            for i in range(28)
        ],
    }


def test_realistic_audit_probe_is_recorder_safe_and_preserves_ledger() -> None:
    audit = _audit()
    projected = compact_roi_reward_audit(audit)
    actual = {**projected, "friendly_name": "KEMS ROI reward audit"}
    result = roi_recorder_probe(audit, actual)
    assert result["live_attribute_bytes_approx"] < RECORDER_LIMIT_BYTES
    assert result["projection_bytes_approx"] < 12_000
    assert result["live_under_recorder_limit"] is True
    assert result["projection_rows_omitted"] == 20
    assert result["full_diagnostic_rows"] == 28
    assert result["database_history_verified"] is False
    assert audit["included_total_pence"] == 1452.396728


def test_actual_oversized_state_is_not_reported_as_recorder_safe() -> None:
    result = roi_recorder_probe(_audit(), {"note": "Y" * 20_000})
    assert result["live_under_recorder_limit"] is False
    assert result["database_history_verified"] is False
    assert roi_recorder_probe(_audit(), None)["live_under_recorder_limit"] is None


def test_power_down_export_baseline_missing_disabled_or_unavailable() -> None:
    eid = "sensor.octopus_export_octoplus_power_down_baseline"
    disabled = power_down_baseline_probe(
        eid, SimpleNamespace(disabled_by=SimpleNamespace(value="integration")), None
    )
    assert disabled["status"] == "disabled_in_entity_registry"
    assert disabled["disabled_by"] == "integration"
    assert power_down_baseline_probe(eid, None, None)["status"] == (
        "not_registered_or_missing_state"
    )
    assert power_down_baseline_probe(
        eid, SimpleNamespace(disabled_by=None), SimpleNamespace(state="unavailable")
    )["status"] == "registered_but_unavailable"
    assert power_down_baseline_probe(
        eid, SimpleNamespace(disabled_by=None), SimpleNamespace(state="0.025")
    )["status"] == "available"


def test_diagnostic_is_read_only_and_exposes_both_probes() -> None:
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "custom_components" / "kems" / "diagnostics.py"
    ).read_text()
    assert "roi_reward_recorder_probe" in source
    assert "power_down_baseline_entity_registry" in source
    assert "registry.entities.get" in source
    assert "async_update_entity" not in source
