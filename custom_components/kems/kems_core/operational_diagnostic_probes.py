"""Read-only Recorder size and external supplier entity-registry evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

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
