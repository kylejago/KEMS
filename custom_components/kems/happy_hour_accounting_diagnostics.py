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
    *,
    roi_reward_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Explain saved financial evidence without assuming missing reward hours."""
    receipts: dict[tuple[datetime, datetime], Mapping[str, Any]] = {}
    for item in verified_receipts:
        if not isinstance(item, Mapping) or not _valid_receipt(item):
            continue
        key = _window(item)
        if key and 55 <= (key[1] - key[0]).total_seconds() / 60 <= 65:
            receipts[key] = item

    # This ledger only accepts COMPLETE witnessed hours. ROI deliberately has a
    # separate, weaker provisional evidence tier for partially witnessed hours.
    # Read both without ever upgrading a provisional estimate into a receipt.
    roi_rows: dict[tuple[datetime, datetime], Mapping[str, Any]] = {}
    audit = roi_reward_audit if isinstance(roi_reward_audit, Mapping) else None
    if audit is not None:
        for row in audit.get("entries", []):
            if not isinstance(row, Mapping) or row.get("type") != "happy_hour":
                continue
            key = _window(row)
            if key and row.get("included_in_roi") is True:
                roi_rows[key] = row

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
        roi_row = roi_rows.get(key, {})
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
                "roi_estimated_credit_pence": roi_row.get("estimated_reward_pence"),
                "roi_evidence_source": roi_row.get("evidence_source"),
                "roi_estimate_status": roi_row.get("status"),
                "roi_coverage_percent": roi_row.get("coverage_percent"),
                "roi_rate_basis": roi_row.get("rate_basis"),
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
    # The ROI summary is authoritative for the complete commissioned-period
    # totals; the bounded itemised entries may be truncated in diagnostics.
    roi_total = (
        audit.get("included_happy_hour_pence")
        if audit is not None
        else None
    )
    roi_provisional = (
        audit.get("provisional_partial_pence")
        if audit is not None
        else None
    )
    comparison_complete = bool(
        audit is not None
        and audit.get("entries_omitted", 0) == 0
        and isinstance(roi_total, (int, float))
        and isfinite(roi_total)
        and isinstance(roi_provisional, (int, float))
        and isfinite(roi_provisional)
    )
    verified_counted_in_roi = sum(
        float(receipts[key]["credit_pence"])
        for key, row in roi_rows.items()
        if key in receipts
        and row.get("evidence_source") == "completed_meter_and_tariff_verified_hour"
    )
    difference = (
        round(roi_total - roi_provisional - verified_counted_in_roi, 3)
        if comparison_complete
        else None
    )
    return {
        "hour_evidence": evidence[-24:],
        "hour_evidence_omitted": max(len(evidence) - 24, 0),
        "completed_verified_receipts": len(receipts),
        "recorded_unverified_windows": sum(
            1
            for row in evidence
            if "incomplete" in row["status"]
            or "not_independent" in row["status"]
            or "missing_independent" in row["status"]
        ),
        "physical_meter_last_saved_sample": persisted_ledger_status.get("last_sample"),
        "supplier_credit_settled": False,
        "roi_reconciliation": {
            "status": (
                "reconciled_estimate_tiers"
                if difference is not None and abs(difference) <= 0.05
                else "needs_evidence_review" if difference is not None
                else "not_comparable"
            ),
            "scope": "financially_commissioned_happy_hour_rewards",
            "roi_included_estimate_pence": roi_total if comparison_complete else None,
            "roi_provisional_partial_pence": (
                roi_provisional if comparison_complete else None
            ),
            "verified_hour_credit_counted_in_roi_pence": (
                round(verified_counted_in_roi, 3)
                if comparison_complete else None
            ),
            "unexplained_difference_pence": difference,
            "supplier_confirmed_credit_pence": None,
            "note": (
                "ROI includes independently booked, partially witnessed provisional "
                "meter credit; the complete-hour receipt ledger excludes those "
                "hours until full meter-and-tariff proof arrives. Neither tier "
                "confirms Octopus settlement. Agile export income is separate."
            ),
        },
        "explanation": (
            "Saved credits are estimates, not Octopus settlement. A grouped booking "
            "cannot prove two one-hour rewards; incomplete physical or historical "
            "tariff data cannot be interpolated. Missing hours remain uncredited."
        ),
        "reporting_only": True,
    }
