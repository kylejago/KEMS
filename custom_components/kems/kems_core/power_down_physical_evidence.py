"""Home Assistant-independent physical grid metering for Power Down audits.

No hardware writes and no financial settlement; only fresh event-time meter
evidence with bounded integration across contiguous observed intervals.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

from .models import Snapshot


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if isfinite(result) else None


def _observe_physical_grid(
    pending: dict[str, Any], snapshot: Snapshot, now: datetime
) -> None:
    """Record independent physical meter evidence, not modelled site output.

    Never extrapolate the first reading back to the event start. Accept only
    contiguous <=150-second pairs within an active joined session; exclude
    missing/stale/ambiguous meter readings. An unchanged zero is valid.
    """
    start = datetime.fromisoformat(str(pending["session_start"]))
    end = datetime.fromisoformat(str(pending["session_end"]))
    if not (
        start <= now < end
        and snapshot.saving_session_active
        and snapshot.saving_session_joined
    ):
        return
    if {"grid_import_kw", "grid_export_kw"} & set(snapshot.stale_fields):
        pending.pop("_physical_last_at", None)
        return
    imported = _number(snapshot.grid_import_kw)
    exported = _number(snapshot.grid_export_kw)
    if (
        imported is None
        or exported is None
        or imported < 0.0
        or exported < 0.0
        or (imported > 0.01 and exported > 0.01)
    ):
        pending.pop("_physical_last_at", None)
        return
    last_at = pending.get("_physical_last_at")
    if isinstance(last_at, str):
        previous = datetime.fromisoformat(last_at)
        seconds = (now - previous).total_seconds()
        if 0.0 < seconds <= 150.0 and previous >= start:
            hours = seconds / 3600.0
            pending["_physical_coverage_hours"] = (
                float(pending.get("_physical_coverage_hours", 0.0)) + hours
            )
            pending["_physical_export_kwh"] = (
                float(pending.get("_physical_export_kwh", 0.0))
                + max(float(pending.get("_physical_last_export_kw", 0.0)), 0.0) * hours
            )
            pending["_physical_import_kwh"] = (
                float(pending.get("_physical_import_kwh", 0.0))
                + max(float(pending.get("_physical_last_import_kw", 0.0)), 0.0) * hours
            )
    pending["_physical_last_at"] = now.isoformat()
    pending["_physical_last_export_kw"] = exported
    pending["_physical_last_import_kw"] = imported
    pending["_physical_samples"] = int(pending.get("_physical_samples", 0)) + 1


def _physical_event_result(pending: dict[str, Any]) -> dict[str, Any]:
    """Classify physical delivery without claiming supplier settlement."""
    start = datetime.fromisoformat(str(pending["session_start"]))
    end = datetime.fromisoformat(str(pending["session_end"]))
    duration = max((end - start).total_seconds() / 3600.0, 0.0)
    coverage = float(pending.get("_physical_coverage_hours", 0.0))
    samples = int(pending.get("_physical_samples", 0))
    sufficient = duration > 0.0 and coverage >= duration * 0.75 and samples >= 2
    measured = round(float(pending.get("_physical_export_kwh", 0.0)), 3)
    return {
        "physical_grid_export_kwh": measured if samples else None,
        "physical_grid_import_kwh": (
            round(float(pending.get("_physical_import_kwh", 0.0)), 3)
            if samples
            else None
        ),
        "physical_coverage_hours": round(coverage, 3),
        "physical_samples_observed": samples,
        "physical_export_verified": measured >= 0.1 if sufficient else None,
        "physical_evidence_status": (
            "verified_physical_grid_export"
            if sufficient and measured >= 0.1
            else (
                "no_significant_physical_export"
                if sufficient
                else "insufficient_physical_meter_coverage"
            )
        ),
        "supplier_settled": False,
    }
