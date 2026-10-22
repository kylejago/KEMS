"""Alpha9.124: commissioning entity must never overflow Recorder attributes."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from kems_core.commissioning_presentation import (
    COMMISSIONING_ATTRIBUTES_BUDGET_BYTES,
    recorder_safe_commissioning_attributes,
)

ROOT = Path(__file__).resolve().parents[1]
COMMISSIONING = ROOT / "custom_components/kems/commissioning.py"
DIAGNOSTICS = ROOT / "custom_components/kems/diagnostics.py"
RECORDER_CEILING_BYTES = 16_384


def _sample(check_count: int = 27) -> dict:
    checks = [
        {
            "key": f"check_{i}",
            "label": f"Commissioning check {i}",
            "status": "PASS" if i % 5 else "WAIT",
            "required": True,
            "detail": "reason and physical proof " * 130,
        }
        for i in range(check_count)
    ]
    return {
        "state": "Collecting evidence",
        "ready_for_shadow": False,
        "ready_for_control": False,
        "maximum_allowed_stage": "shadow",
        "real_hardware_writes": "blocked",
        "pass_count": sum(x["status"] == "PASS" for x in checks),
        "wait_count": sum(x["status"] == "WAIT" for x in checks),
        "fail_count": 0,
        "required_checks": check_count,
        "checks": checks,
        "foxess_registered_entity_count": 124,
        "foxess_registered_entities": ["sensor.kh7_" + "x" * 800] * 350,
        "physical_source_authority": {"huge": "x" * 120_000},
        "foxess_mappings": {"huge": "y" * 120_000},
        "restart_commissioning_live_power_balance": {"detail": "z" * 120_000},
        "foxess_telemetry_stability": {
            "state": "stable",
            "ready": True,
            "samples": 60,
            "complete_samples": 60,
            "completeness_percent": 100.0,
            "failed_samples": [{"detail": "x" * 120_000}],
        },
        "foxess_power_balance": {
            "state": "balanced",
            "ready": True,
            "samples": 60,
            "eligible_samples": 60,
            "balanced_samples": 60,
            "balance_percent": 100.0,
            "maximum_absolute_residual_kw": 0.2,
            "failed_samples": [{"detail": "x" * 120_000}],
        },
        "foxess_battery_direction_evidence": {
            "state": "proven",
            "confidence_percent": 99.9,
            "votes": [{"detail": "x" * 120_000}],
        },
        "limits": {"inverter_limit_kw": 7.0, "export_limit_kw": 7.0},
        "shadow_command": {"recent_event": "x" * 120_000},
    }


def _size(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=True).encode("utf-8"))


def test_recorder_projection_is_far_below_byte_limit_without_losing_flags() -> None:
    raw = _sample()
    original = deepcopy(raw)
    assert _size(raw) > RECORDER_CEILING_BYTES
    result = recorder_safe_commissioning_attributes(raw)
    assert _size(result) <= COMMISSIONING_ATTRIBUTES_BUDGET_BYTES
    assert COMMISSIONING_ATTRIBUTES_BUDGET_BYTES < RECORDER_CEILING_BYTES
    assert result["ready_for_control"] is False
    assert result["required_checks"] == 27
    assert result["pass_count"] == 21
    assert result["wait_count"] == 6
    assert len(result["checks"]) == 27
    assert any(x["status"] == "WAIT" for x in result["checks"])
    assert "foxess_registered_entities" not in result
    assert "physical_source_authority" not in result
    assert "restart_commissioning_live_power_balance" not in result
    assert result["foxess_power_balance"]["balance_percent"] == 100.0
    assert raw == original


def test_checklist_remains_bounded_if_future_KEMS_adds_hundreds_of_checks() -> None:
    raw = _sample(check_count=400)
    result = recorder_safe_commissioning_attributes(raw)
    assert _size(result) <= COMMISSIONING_ATTRIBUTES_BUDGET_BYTES
    assert result["checks_total"] == 400
    assert result["checks_omitted"] > 0
    assert result["fail_count"] == 0


def test_dynamic_text_and_large_limits_cannot_bypass_budget() -> None:
    raw = _sample()
    raw["maximum_allowed_stage"] = "s" * 100_000
    raw["limits"] = {f"limit_{i}": i for i in range(15_000)}
    result = recorder_safe_commissioning_attributes(raw)
    assert _size(result) <= COMMISSIONING_ATTRIBUTES_BUDGET_BYTES
    assert result["ready_for_control"] is False
    assert result["wait_count"] == 6


def test_new_projection_only_changes_sensor_presentation_not_real_gates() -> None:
    source = COMMISSIONING.read_text(encoding="utf-8")
    diagnostics = DIAGNOSTICS.read_text(encoding="utf-8")
    assert "return recorder_safe_commissioning_attributes(payload)" in source
    assert (
        'return str(build_commissioning_snapshot(self._hass, self.coordinator)["state"])'
        in source
    )
    assert '"commissioning": build_commissioning_snapshot(' in diagnostics
    assert "recorder_safe_commissioning_attributes" not in diagnostics
    assert '"checks": checks,' in source
    assert '"ready_for_control": ready_for_control,' in source
