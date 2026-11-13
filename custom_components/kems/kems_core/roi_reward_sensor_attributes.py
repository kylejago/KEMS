"""Bounded Home Assistant sensor view of the complete KEMS reward audit.

The independent reward ledger and the full integration diagnostics are not
truncated. Only the Recorder-facing entity attributes are reduced so Home
Assistant can retain their history below its 16 KiB attribute limit.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

MAX_SENSOR_ATTRIBUTES_BYTES = 12_000
MAX_SENSOR_ENTRIES = 8

_SUMMARY_FIELDS = (
    "schema_version",
    "reporting_only",
    "supplier_settlement_available",
    "supplier_awarded_power_down_pence",
    "supplier_settled_pence",
    "included_estimate_pence",
    "included_happy_hour_pence",
    "included_power_down_pence",
    "included_total_pence",
    "unsettled_total_pence",
    "provisional_partial_pence",
    "meter_supported_estimate_pence",
    "included_count",
    "pending_count",
)


def _byte_count(value: dict[str, Any]) -> int:
    """Measure UTF-8 JSON with a margin for Recorder's serialisation."""
    return len(
        json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode("utf-8")
    )


def compact_roi_reward_audit(audit: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve exact financial totals and as many recent event rows as fit.

    Truncation is explicit and applies only to the HA entity attributes.
    Diagnostic `roi_reward_audit` remains complete, including all included
    and pending events. No amount or supplier-settlement status is fabricated.
    """
    attrs = {key: audit[key] for key in _SUMMARY_FIELDS if key in audit}
    coverage = audit.get("historical_coverage")
    if isinstance(coverage, Mapping):
        attrs["historical_coverage"] = {
            key: value
            for key, value in coverage.items()
            if key != "note" and isinstance(value, (bool, int, float, str, type(None)))
        }
        if coverage.get("note"):
            attrs["historical_coverage"]["note"] = str(coverage["note"])[:320]

    if audit.get("note"):
        attrs["note"] = str(audit["note"])[:640]

    rows = audit.get("entries")
    all_rows = rows if isinstance(rows, list) else []
    attrs["entries"] = [
        dict(item) for item in all_rows[:MAX_SENSOR_ENTRIES] if isinstance(item, dict)
    ]
    try:
        upstream_omitted = max(int(audit.get("entries_omitted") or 0), 0)
    except (TypeError, ValueError):
        upstream_omitted = 0

    attrs["entries_omitted"] = upstream_omitted + len(all_rows) - len(attrs["entries"])
    attrs["full_entries_in_diagnostics"] = True
    attrs["event_details_source"] = "KEMS diagnostics: roi_reward_audit.entries"

    while attrs["entries"] and _byte_count(attrs) > MAX_SENSOR_ATTRIBUTES_BYTES:
        attrs["entries"].pop()
        attrs["entries_omitted"] += 1

    # A future audit schema could contain oversized notes. Keep totals and
    # provenance, rather than allowing Recorder to drop *all* attributes.
    if _byte_count(attrs) > MAX_SENSOR_ATTRIBUTES_BYTES:
        attrs.pop("note", None)
        coverage_attrs = attrs.get("historical_coverage")
        if isinstance(coverage_attrs, dict):
            coverage_attrs.pop("note", None)

    attrs["sensor_entries_truncated"] = bool(attrs["entries_omitted"])
    return attrs
