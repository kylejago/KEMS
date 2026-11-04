"""Alpha9.179: explain separate provisional and completed Happy Hour ledgers."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

FILE = (
    Path(__file__).parents[1]
    / "custom_components"
    / "kems"
    / "happy_hour_accounting_diagnostics.py"
)
spec = importlib.util.spec_from_file_location("kems_hh_accounting_diagnostics", FILE)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(module)
audit_happy_hour = module.build_happy_hour_accounting_audit

START_1 = "2026-11-01T12:00:00+00:00"
END_1 = "2026-11-01T13:00:00+00:00"
START_2 = END_1
END_2 = "2026-11-01T14:00:00+00:00"
VERIFIED = {
    "start": START_1,
    "end": END_1,
    "completed": True,
    "import_kwh": 7.294,
    "credit_pence": 261.729143,
}
WINDOWS = {
    "persisted_reward_windows": [
        {"start": START_1, "end": END_1, "event_id": "8067"},
        {"start": START_1, "end": END_2},  # grouped display, NOT one hour
        {
            "start": START_2,
            "end": END_2,
            "event_id": "8068",
            "booking_source": "octopus_joined_events",
        },
    ]
}
ROI = {
    "included_happy_hour_pence": 378.333269,
    "provisional_partial_pence": 116.604126,
    "entries_omitted": 0,
    "entries": [
        {
            "type": "happy_hour",
            "start": START_1,
            "end": END_1,
            "included_in_roi": True,
            "evidence_source": "completed_meter_and_tariff_verified_hour",
            "estimated_reward_pence": 261.729,
            "status": "included_meter_supported_estimate",
        },
        {
            "type": "happy_hour",
            "start": START_2,
            "end": END_2,
            "included_in_roi": True,
            "evidence_source": "provisional_partial_physical_meter_credit",
            "estimated_reward_pence": 116.604,
            "status": "included_provisional_partial_estimate",
            "coverage_percent": 79.3,
            "rate_basis": "adjacent_verified_hour_indicative_rate_proxy",
        },
    ],
}


def test_provisional_roi_is_visible_without_upgrading_partial_hour_to_verified():
    result = audit_happy_hour(WINDOWS, [VERIFIED], roi_reward_audit=ROI)
    hours = result["hour_evidence"]
    assert len(hours) == 3
    assert result["completed_verified_receipts"] == 1
    assert hours[0]["status"] == "verified_saved_receipt"
    assert hours[0]["roi_estimated_credit_pence"] == pytest.approx(261.729)
    assert hours[1]["status"] == "grouped_window_not_independent_reward_proof"
    assert hours[1]["roi_estimated_credit_pence"] is None
    assert hours[2]["status"] == "booking_verified_but_meter_or_tariff_proof_incomplete"
    assert hours[2]["saved_credit_pence"] is None
    assert hours[2]["roi_estimated_credit_pence"] == pytest.approx(116.604)
    assert hours[2]["roi_coverage_percent"] == pytest.approx(79.3)
    reconciliation = result["roi_reconciliation"]
    assert reconciliation["status"] == "reconciled_estimate_tiers"
    assert reconciliation["roi_included_estimate_pence"] == pytest.approx(378.333269)
    assert reconciliation["roi_provisional_partial_pence"] == pytest.approx(116.604126)
    assert reconciliation["verified_hour_credit_counted_in_roi_pence"] == pytest.approx(
        261.729143
    )
    assert reconciliation["unexplained_difference_pence"] == pytest.approx(0.0)
    assert reconciliation["supplier_confirmed_credit_pence"] is None
    assert result["supplier_credit_settled"] is False


def test_legacy_diagnostic_without_roi_is_explicitly_not_comparable():
    result = audit_happy_hour(WINDOWS, [VERIFIED])
    assert result["roi_reconciliation"]["status"] == "not_comparable"
    assert result["roi_reconciliation"]["unexplained_difference_pence"] is None
    assert result["completed_verified_receipts"] == 1


def test_missing_roi_backed_receipt_surfaces_unexplained_gap():
    modified = dict(ROI, entries=ROI["entries"][1:])
    result = audit_happy_hour(WINDOWS, [VERIFIED], roi_reward_audit=modified)
    assert result["roi_reconciliation"]["status"] == "needs_evidence_review"
    assert result["roi_reconciliation"]["unexplained_difference_pence"] == pytest.approx(
        261.729
    )


def test_truncated_roi_entry_list_is_never_declared_reconciled():
    modified = dict(ROI, entries_omitted=1)
    result = audit_happy_hour(WINDOWS, [VERIFIED], roi_reward_audit=modified)
    assert result["roi_reconciliation"]["status"] == "not_comparable"


def test_diagnostic_wiring_is_reporting_only():
    source = (
        Path(__file__).parents[1] / "custom_components" / "kems" / "diagnostics.py"
    ).read_text(encoding="utf-8")
    assert "roi_reward_audit=data.roi.reward_audit" in source
    assert "supplier_confirmed_credit_pence" in FILE.read_text(encoding="utf-8")
