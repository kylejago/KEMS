"""Read-only evidence status for completed Octopus Happy Hour accounting.

No missing booking or physical meter intervals are reconstructed here.
The output is diagnostic-only and cannot grant free-import authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from typing import Any


def _window(item: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    try:
        start = datetime.fromisoformat(str(item["start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(item["end"]).replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError):
        return None
    if start.tzinfo is None or end.tzinfo is None or end <= start:
        return None
    return start, end


def _valid_receipt(item: Mapping[str, Any]) -> bool:
    try:
        energy = float(item["import_kwh"])
        credit = float(item["credit_pence"])
    except (KeyError, ValueError, TypeError, OverflowError):
        return False
    return (
        bool(item.get("completed"))
        and isfinite(energy)
        and 0 <= energy <= 16.0
        and isfinite(credit)
        and credit >= 0
    )


def build_happy_hour_accounting_audit(
    persisted_ledger_status: Mapping[str, Any],
    verified_receipts: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Explain saved financial evidence without assuming missing reward hours."""
    receipts: dict[tuple[datetime, datetime], Mapping[str, Any]] = {}
    for item in verified_receipts:
        if not isinstance(item, Mapping) or not _valid_receipt(item):
            continue
        key = _window(item)
        if key and 55 <= (key[1] - key[0]).total_seconds() / 60 <= 65:
            receipts[key] = item

    evidence: list[dict[str, Any]] = []
    seen: set[tuple[datetime, datetime]] = set()
    windows = persisted_ledger_status.get("persisted_reward_windows") or []
    for item in windows if isinstance(windows, list) else []:
        if not isinstance(item, Mapping):
            continue
        key = _window(item)
        if key is None:
            continue
        start, end = key
        one_hour = 55 <= (end - start).total_seconds() / 60 <= 65
        independent = bool(
            item.get("event_id")
            or item.get("event_code")
            or item.get("booking_source") == "octopus_joined_events"
        )
        receipt = receipts.get(key)
        if receipt is not None:
            status = "verified_saved_receipt"
        elif not one_hour:
            status = "grouped_window_not_independent_reward_proof"
        elif not independent:
            status = "missing_independent_booking_provenance"
        else:
            status = "booking_verified_but_meter_or_tariff_proof_incomplete"
        seen.add(key)
        evidence.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "status": status,
                "event_id": item.get("event_id"),
                "booking_source": item.get("booking_source"),
                "saved_credit_pence": (
                    float(receipt["credit_pence"]) if receipt is not None else None
                ),
                "saved_eligible_import_kwh": (
                    float(receipt["import_kwh"]) if receipt is not None else None
                ),
            }
        )
    for key, receipt in receipts.items():
        if key not in seen:
            evidence.append(
                {
                    "start": key[0].isoformat(),
                    "end": key[1].isoformat(),
                    "status": "verified_archived_receipt",
                    "saved_credit_pence": float(receipt["credit_pence"]),
                    "saved_eligible_import_kwh": float(receipt["import_kwh"]),
                }
            )

    evidence.sort(key=lambda row: (row["start"], row["end"]))
    return {
        "hour_evidence": evidence[-24:],
        "hour_evidence_omitted": max(len(evidence) - 24, 0),
        "completed_verified_receipts": len(receipts),
        "recorded_unverified_windows": sum(
            1 for row in evidence if "incomplete" in row["status"]
            or "not_independent" in row["status"]
            or "missing_independent" in row["status"]
        ),
        "physical_meter_last_saved_sample": persisted_ledger_status.get(
            "last_sample"
        ),
        "supplier_credit_settled": False,
        "explanation": (
            "Saved credits are estimates, not Octopus settlement. A grouped booking "
            "cannot prove two one-hour rewards; incomplete physical or historical "
            "tariff data cannot be interpolated. Missing hours remain uncredited."
        ),
        "reporting_only": True,
    }
