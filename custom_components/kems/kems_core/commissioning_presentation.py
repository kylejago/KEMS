"""Small, Recorder-safe Home Assistant projection of commissioning evidence.

The full build_commissioning_snapshot() stays untouched and remains available
in the KEMS diagnostics download. This module is presentation ONLY and has no
Home Assistant dependencies or inverter/control write authority.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

# Leave ample margin below Home Assistant Recorder's 16,384-byte limit,
# including state metadata, UTF-8 encoding differences and future fields.
COMMISSIONING_ATTRIBUTES_BUDGET_BYTES = 8_192

_SUMMARY_FIELDS = (
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
    "restart_commissioning_proof_available",
    "restart_commissioning_proof_matches",
    "restart_commissioning_live_evidence_consistent",
    "restart_commissioning_bridge_active",
    "foxess_site_telemetry_proof_ready",
    "foxess_telemetry_proof_ready",
    "configured_battery_power_positive_is_discharge",
    "detected_battery_power_positive_is_discharge",
    "battery_direction_evidence_samples",
    "battery_direction_confidence_percent",
    "tariff_freshness_reconciled",
)
_EVIDENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "foxess_telemetry_stability": (
        "state", "ready", "samples", "complete_samples", "completeness_percent",
        "maximum_gap_seconds",
    ),
    "foxess_power_balance": (
        "state", "ready", "samples", "eligible_samples", "balanced_samples",
        "balance_percent", "maximum_absolute_residual_kw",
    ),
    "foxess_battery_direction_evidence": (
        "state", "ready", "evidence_samples", "confidence_percent",
        "positive_is_discharge_votes", "positive_is_charge_votes",
    ),
}


def _text(value: Any, maximum: int) -> str:
    """Bound even unexpected third-party/HASS text to predictable attributes."""
    return str(value or "")[:maximum]


def _bytes(value: Mapping[str, Any]) -> int:
    # ensure_ascii=True is deliberately conservative for non-ASCII HA strings.
    return len(json.dumps(value, ensure_ascii=True, default=str).encode("utf-8"))


def recorder_safe_commissioning_attributes(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep status/checklist in Recorder without replicating diagnostic trees.

    The live decision and its complete physical/source evidence are unchanged.
    The rich source mappings, raw rolling evidence and deep check details stay
    in the integration diagnostics, not in a 60-second Recorder state update.
    """
    attributes: dict[str, Any] = {
        key: payload[key]
        for key in _SUMMARY_FIELDS
        if key in payload
        and (payload[key] is None or isinstance(payload[key], (str, int, float, bool)))
    }
    attributes["diagnostic_detail_location"] = "KEMS integration diagnostics"
    for name, fields in _EVIDENCE_FIELDS.items():
        evidence = payload.get(name)
        if isinstance(evidence, Mapping):
            attributes[name] = {
                key: value
                for key in fields
                if (value := evidence.get(key)) is not None
                and isinstance(value, (str, int, float, bool))
            }

    checks = payload.get("checks")
    checks = checks if isinstance(checks, (tuple, list)) else ()
    attributes["checks_total"] = len(checks)
    # Preserve the existing 'checks' list for dashboards while limiting every
    # label/detail and excluding all diagnostic/source subtrees.
    compact = []
    for item in checks[:48]:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {
            "key": _text(item.get("key"), 72),
            "label": _text(item.get("label"), 96),
            "status": _text(item.get("status"), 20),
            "required": item.get("required") is True,
        }
        if item.get("status") != "PASS":
            entry["detail"] = _text(item.get("detail"), 180)
        compact.append(entry)
    attributes["checks"] = compact
    attributes["checks_omitted"] = max(len(checks) - len(compact), 0)
    limits = payload.get("limits")
    if isinstance(limits, Mapping):
        attributes["limits"] = {
            _text(key, 40): value
            for key, value in limits.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }

    if _bytes(attributes) > COMMISSIONING_ATTRIBUTES_BUDGET_BYTES:
        # Always keep concise PASS/WAIT/FAIL flags, not long human prose.
        for item in compact:
            item.pop("detail", None)
            item.pop("label", None)
    if _bytes(attributes) > COMMISSIONING_ATTRIBUTES_BUDGET_BYTES:
        # A future massively expanded commissioning checklist cannot recreate
        # the Recorder overflow. Use a deterministic bounded subset.
        attributes["checks"] = compact[:24]
        attributes["checks_omitted"] = max(
            len(checks) - len(attributes["checks"]), 0
        )
    if _bytes(attributes) > COMMISSIONING_ATTRIBUTES_BUDGET_BYTES:
        attributes["checks"] = compact[:8]
        attributes["checks_omitted"] = max(len(checks) - len(attributes["checks"]), 0)
    if _bytes(attributes) > COMMISSIONING_ATTRIBUTES_BUDGET_BYTES:
        attributes["checks"] = []
        attributes["checks_omitted"] = len(checks)
        attributes.pop("limits", None)
        for key in _EVIDENCE_FIELDS:
            attributes.pop(key, None)

    # All remaining keys are fixed-size scalars; the compact result must
    # remain well below the actual 16 KiB Recorder ceiling.
    return attributes
