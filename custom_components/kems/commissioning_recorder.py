"""Bounded commissioning SENSOR attributes for Home Assistant Recorder.

The authoritative commissioning readiness gate and complete assessment remain
unchanged in commissioning.build_commissioning_snapshot(), which diagnostics
still publishes in full. Only the entity's presentation is compacted here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

# Keep the whole user-sensor payload comfortably below Recorder's 16384-byte
# attributes ceiling, including entity/HA-added metadata. The bounded field
# list is intentionally explicit: adding new diagnostics cannot silently
# enlarge Recorder rows.
COMMISSIONING_SENSOR_ATTRIBUTE_BUDGET_BYTES = 8192
_MAX_CHECKS = 48
_MAX_CHECK_KEY = 64
_MAX_CHECK_LABEL = 80
_MAX_CHECK_DETAIL = 140

_SCALAR_KEYS = (
    "ready_for_shadow",
    "ready_for_control",
    "maximum_allowed_stage",
    "real_hardware_writes",
    "pass_count",
    "wait_count",
    "fail_count",
    "required_checks",
    "foxess_registered_entity_count",
    "battery_installation_pending",
    "solar_only_commissioning",
    "foxess_site_mapping_gate_passed",
    "foxess_telemetry_mapping_gate_passed",
    "foxess_site_evidence_sources_ready",
    "foxess_evidence_sources_ready",
    "fresh_foxess_telemetry_proof_ready",
    "foxess_site_telemetry_proof_ready",
    "foxess_telemetry_proof_ready",
    "restart_commissioning_proof_available",
    "restart_commissioning_proof_matches",
    "restart_commissioning_live_evidence_consistent",
    "restart_commissioning_bridge_active",
    "configured_battery_power_positive_is_discharge",
    "detected_battery_power_positive_is_discharge",
    "battery_direction_evidence_samples",
    "battery_direction_confidence_percent",
)
_EVIDENCE_KEYS = {
    "foxess_telemetry_stability": (
        "state",
        "samples",
        "complete_samples",
        "completeness_percent",
        "maximum_gap_seconds",
        "allowed_gap_seconds",
    ),
    "foxess_power_balance": (
        "state",
        "samples",
        "eligible_samples",
        "balanced_samples",
        "balance_percent",
        "mean_absolute_residual_kw",
        "maximum_absolute_residual_kw",
    ),
    "foxess_battery_direction_evidence": (
        "state",
        "evidence_samples",
        "confidence_percent",
        "positive_is_discharge",
        "positive_is_discharge_votes",
        "positive_is_charge_votes",
    ),
}


def _simple(value: Any, *, max_text: int = 100) -> str | bool | int | float | None:
    """Restrict Recorder-facing values to scalar/bounded immutable data."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:max_text]


def _check(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "key": _simple(item.get("key"), max_text=_MAX_CHECK_KEY),
        "label": _simple(item.get("label"), max_text=_MAX_CHECK_LABEL),
        "status": _simple(item.get("status"), max_text=12),
        "required": bool(item.get("required", True)),
        "detail": _simple(item.get("detail"), max_text=_MAX_CHECK_DETAIL),
    }


def _byte_size(attributes: dict[str, Any]) -> int:
    # Default spacing and unicode escaping are close to HA's JSON encoding;
    # test the conservative default rather than unusually compact JSON.
    return len(json.dumps(attributes, ensure_ascii=True).encode("utf-8"))


def commissioning_recorder_attributes(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a hard-bounded, readable commissioning sensor attribute mapping.

    Oversized lists, raw entity mappings, session evidence, and physical
    replay records remain exclusively in the downloadable KEMS diagnostics.
    A bounded PASS/WAIT/FAIL checklist is retained for existing live UI.
    """
    result: dict[str, Any] = {
        key: _simple(payload.get(key)) for key in _SCALAR_KEYS
    }
    for key, fields in _EVIDENCE_KEYS.items():
        evidence = payload.get(key)
        if isinstance(evidence, Mapping):
            result[key] = {
                field: _simple(evidence.get(field)) for field in fields
                if field in evidence
            }

    # Keep WAIT/FAIL reasons visible if the checklist grows beyond its old
    # shape. The original status totals and total list count stay accurate.
    raw_checks = payload.get("checks")
    source = (
        [check for check in raw_checks if isinstance(check, Mapping)]
        if isinstance(raw_checks, list) else []
    )
    ordered = sorted(
        enumerate(source),
        key=lambda entry: (
            str(entry[1].get("status")) == "PASS",
            entry[0],
        ),
    )
    selected = ordered[:_MAX_CHECKS]
    selected.sort(key=lambda entry: entry[0])
    result["checks"] = [_check(item) for _, item in selected]
    result["check_count_total"] = len(source)
    result["check_count_omitted"] = max(len(source) - len(selected), 0)
    result["full_evidence_location"] = "KEMS integration diagnostics"
    result["recorder_bounded"] = True

    # A defensive second bound protects against future longer labels or
    # additional evidence fields. Do not silently truncate the actual
    # commissioning snapshot or weaken the gate; only trim presentation.
    if _byte_size(result) > COMMISSIONING_SENSOR_ATTRIBUTE_BUDGET_BYTES:
        for check in result["checks"]:
            if check["status"] == "PASS":
                check["detail"] = None
    while (
        _byte_size(result) > COMMISSIONING_SENSOR_ATTRIBUTE_BUDGET_BYTES
        and result["checks"]
    ):
        result["checks"].pop()
        result["check_count_omitted"] += 1

    # All remaining keys are fixed-size primitives. Still guard any future
    # additions by dropping optional evidence ahead of the readiness flags.
    if _byte_size(result) > COMMISSIONING_SENSOR_ATTRIBUTE_BUDGET_BYTES:
        for key in _EVIDENCE_KEYS:
            result.pop(key, None)
    return result
