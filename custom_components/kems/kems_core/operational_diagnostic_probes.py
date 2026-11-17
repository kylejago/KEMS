"""Read-only Recorder size and external supplier entity-registry evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from typing import Any

from .counter_evidence import MAX_SAMPLE_AGE_SECONDS
from .roi_reward_sensor_attributes import (
    MAX_SENSOR_ATTRIBUTES_BYTES,
    compact_roi_reward_audit,
)

RECORDER_LIMIT_BYTES = 16_384


def _byte_size(attributes: Mapping[str, Any]) -> int:
    return len(
        json.dumps(
            dict(attributes), ensure_ascii=False, separators=(",", ":"), default=str
        ).encode("utf-8")
    )


def roi_recorder_probe(
    audit: Mapping[str, Any], live_attributes: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Measure actual HA in-memory entity attributes; never assert DB storage."""
    projected = compact_roi_reward_audit(audit)
    live_size = _byte_size(live_attributes) if live_attributes is not None else None
    return {
        "entity_id": "sensor.kems_roi_reward_audit",
        "live_entity_present": live_attributes is not None,
        "live_attribute_bytes_approx": live_size,
        "projection_bytes_approx": _byte_size(projected),
        "projection_budget_bytes": MAX_SENSOR_ATTRIBUTES_BYTES,
        "recorder_limit_bytes": RECORDER_LIMIT_BYTES,
        "live_under_recorder_limit": (
            live_size < RECORDER_LIMIT_BYTES if live_size is not None else None
        ),
        "projection_rows_kept": len(projected.get("entries", [])),
        "projection_rows_omitted": projected.get("entries_omitted", 0),
        "full_diagnostic_rows": len(audit.get("entries") or []),
        "database_history_verified": False,
        "note": (
            "Live attributes only; check HA Core Recorder logs or history "
            "to independently verify persisted attribute history."
        ),
    }


def power_down_baseline_probe(
    entity_id: str | None,
    registered_entity: Any | None,
    state: Any | None,
) -> dict[str, Any]:
    """Distinguish disabled, missing, and temporarily unavailable baselines."""
    disabled = getattr(registered_entity, "disabled_by", None)
    if not entity_id:
        status = "not_configured"
    elif disabled is not None:
        status = "disabled_in_entity_registry"
    elif registered_entity is None and state is None:
        status = "not_registered_or_missing_state"
    elif state is None:
        status = "registered_no_live_state"
    elif getattr(state, "state", None) in ("unknown", "unavailable"):
        status = "registered_but_unavailable"
    else:
        status = "available"
    return {
        "entity_id": entity_id,
        "registered": registered_entity is not None,
        "disabled_by": (
            getattr(disabled, "value", str(disabled)) if disabled is not None else None
        ),
        "state_exists": state is not None,
        "status": status,
        "requires_attention": status != "available",
        "note": (
            "An absent export baseline never implies zero export or "
            "a supplier-awarded Power Down reward."
        ),
    }


def foxess_import_counter_candidate_probe(
    *,
    source_entity_id: str,
    source_registry: Any | None,
    candidates: Mapping[str, tuple[Any | None, Any | None]],
    now: datetime,
) -> dict[str, Any]:
    """Observe *possible* KH7 cumulative meters, never authorise recovery.

    One numeric total cannot establish a monotonic meter, reset behaviour,
    counter epoch or an anchored reward-hour import. Read-only HA lookup.
    """
    source_device = getattr(source_registry, "device_id", None)
    source_config_entry = getattr(source_registry, "config_entry_id", None)
    rows: dict[str, dict[str, Any]] = {}
    for label, (registered, state) in candidates.items():
        disabled = getattr(registered, "disabled_by", None)
        raw = getattr(state, "state", None)
        attrs = getattr(state, "attributes", None) or {}
        unit = attrs.get("unit_of_measurement")
        state_class = attrs.get("state_class")
        device_id = getattr(registered, "device_id", None)
        config_entry = getattr(registered, "config_entry_id", None)
        same_device = (
            source_device == device_id
            if source_device is not None and device_id is not None
            else None
        )
        same_config_entry = (
            source_config_entry == config_entry
            if source_config_entry is not None and config_entry is not None
            else None
        )
        at = getattr(state, "last_reported", None) or getattr(
            state, "last_updated", None
        )
        seconds = (
            max(0.0, (now - at).total_seconds())
            if isinstance(at, datetime) and at.tzinfo is not None
            else None
        )
        try:
            value = float(raw) if raw is not None else None
        except (ValueError, TypeError, OverflowError):
            value = None
        numeric = value is not None and isfinite(value) and value >= 0
        if disabled is not None:
            status = "disabled"
        elif registered is None:
            status = "not_registered"
        elif state is None:
            status = "registered_no_live_state"
        elif raw in {"unknown", "unavailable", None}:
            status = "unavailable"
        elif not numeric:
            status = "invalid_or_non_numeric"
        elif unit != "kWh":
            status = "not_kwh"
        elif state_class not in {"total", "total_increasing"}:
            status = "not_cumulative_state_class"
        elif same_device is False or same_config_entry is False:
            status = "different_registry_device_or_entry"
        else:
            status = "single_reading_only_unverified"
        rows[label] = {
            "entity_id": (
                source_entity_id + "_energy_total"
                if label == "lifetime_total"
                else source_entity_id + "_energy_today"
            ),
            "registry_present": registered is not None,
            "disabled_by": (
                getattr(disabled, "value", str(disabled))
                if disabled is not None
                else None
            ),
            "state": raw,
            "unit": unit,
            "state_class": state_class,
            "age_seconds": round(seconds, 1) if seconds is not None else None,
            "fresh_report_for_evidence_capture": bool(
                status == "single_reading_only_unverified"
                and seconds is not None
                and seconds <= MAX_SAMPLE_AGE_SECONDS
            ),
            "source_device_match": same_device,
            "source_config_entry_match": same_config_entry,
            "candidate_status": status,
            "observed_kwh": round(value, 6) if numeric and unit == "kWh" else None,
            "monotonic_history_verified": False,
            "restart_delta_usable": False,
        }
    return {
        "source_import_power_entity": source_entity_id,
        "candidates": rows,
        "reporting_only": True,
        "counter_capture_requires_fresh_report_seconds": MAX_SAMPLE_AGE_SECONDS,
        "counter_source_approved": False,
        "long_gap_recovery_enabled": False,
        "reward_hour_cap_kwh": 16,
        "next_validation": (
            "Compare multiple timestamped readings with independently measured "
            "grid import, confirm matching physical device, monotonicity, resets, "
            "reward-hour start anchor and strictly bounded unobserved intervals."
        ),
        "note": (
            "Candidate names only; a single value and HA state_class do not "
            "prove a physical cumulative meter. No rewards or charge authority "
            "are inferred from this probe."
        ),
    }
