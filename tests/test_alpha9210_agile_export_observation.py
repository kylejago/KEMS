"""Alpha9.210: evidence-only planned-versus-observed Agile export diagnostics."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "kems"
    / "kems_core"
    / "diagnostic_evidence.py"
)
SPEC = importlib.util.spec_from_file_location("alpha9210_export_diagnostics", SOURCE)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def _slot(begin: datetime, rate: float, shadow: float) -> dict:
    return {
        "valid_from": begin.isoformat(),
        "valid_to": (begin + timedelta(minutes=30)).isoformat(),
        "rate_pence": rate,
        "grid_export_kwh": shadow,
        "settlement_source": "settled shadow digital-twin outcome",
    }


def _record(at: datetime, kw: float, *, stale: bool = False):
    return SimpleNamespace(
        timestamp=at,
        grid_export_kw=kw,
        stale_fields=("grid_export_kw",) if stale else (),
    )


def _run(slots, records, now):
    return audit.agile_export_interval_audit(
        records=records,
        agile_state={"today_slots": slots},
        now=now,
        reported_grid_export_kwh=0.5,
        reported_income_pence=6.0,
        activation_cutoff="2026-11-10T00:00:00+00:00",
    )


def test_boundary_reference_splits_same_samples_without_changing_income() -> None:
    start = datetime(2026, 11, 10, 19, tzinfo=UTC)
    slots = [_slot(start, 12.0, 0.5), _slot(start + timedelta(minutes=30), 14.0, 0.5)]
    original = deepcopy(slots)
    records = [
        _record(start + timedelta(minutes=25), 2.0),
        _record(start + timedelta(minutes=40), 0.0),
    ]
    result = _run(slots, records, start + timedelta(minutes=65))
    assert result["sample_priced_income_pence"] == 6.0
    assert result["snapshot_integrated_export_all_elapsed_kwh"] == 0.5
    assert result["boundary_reference_export_completed_kwh"] == 0.5
    assert result["boundary_reference_reallocated_kwh"] == pytest.approx(0.3333)
    assert result["boundary_reference_priced_income_pence"] == pytest.approx(6.67)
    assert result["boundary_reference_unmatched_kwh"] == 0.0
    assert result["rows"][0]["boundary_reference_export_kwh"] == pytest.approx(0.1667)
    assert result["rows"][1]["boundary_reference_export_kwh"] == pytest.approx(0.3333)
    assert slots == original


def test_boundary_reference_fails_closed_on_unpublished_second_slot() -> None:
    start = datetime(2026, 11, 10, 19, tzinfo=UTC)
    records = [
        _record(start + timedelta(minutes=25), 2.0),
        _record(start + timedelta(minutes=40), 0.0),
    ]
    result = _run([_slot(start, 12.0, 0.5)], records, start + timedelta(minutes=65))
    assert result["sample_priced_income_pence"] == 6.0
    assert result["boundary_reference_unmatched_kwh"] == pytest.approx(0.3333)
    assert result["boundary_reference_priced_income_pence"] is None


def test_boundary_reference_preserves_repeated_dst_hour_with_utc_offsets() -> None:
    start = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    slots = [_slot(start, 12.0, 0.2), _slot(start + timedelta(minutes=30), 14.0, 0.4)]
    records = [
        _record(start + timedelta(minutes=25), 2.0),
        _record(start + timedelta(minutes=40), 0.0),
    ]
    result = audit.agile_export_interval_audit(
        records=records,
        agile_state={"today_slots": slots},
        now=start + timedelta(minutes=65),
        reported_grid_export_kwh=0.5,
        reported_income_pence=6.0,
        activation_cutoff=start.isoformat(),
    )
    assert result["boundary_reference_export_completed_kwh"] == pytest.approx(0.5)
    assert result["boundary_reference_reallocated_kwh"] == pytest.approx(0.3333)


@pytest.mark.parametrize(
    ("requested", "permitted", "desired", "observed", "authorised", "status"),
    [
        (0.0, 0.0, 0.0, 0.0, True, "waiting_for_selected_agile_export"),
        (4.0, 0.0, 0.0, 0.0, True, "physical_reserve_guard_blocked_request"),
        (4.0, 4.0, 0.0, 0.0, True, "planner_request_not_in_final_control"),
        (
            4.0,
            4.0,
            4.0,
            0.0,
            True,
            "authorised_export_not_yet_observed_in_single_snapshot",
        ),
        (4.0, 4.0, 4.0, 3.5, True, "grid_export_observed"),
        (4.0, 4.0, 4.0, 0.0, False, "control_gate_not_authorised"),
    ],
)
def test_single_scan_export_evidence_never_claims_settlement(
    requested, permitted, desired, observed, authorised, status
) -> None:
    snapshot = SimpleNamespace(
        timestamp=datetime(2026, 11, 16, 17, tzinfo=UTC),
        grid_export_kw=observed,
        grid_import_kw=0.0,
        battery_soc=29.0,
    )
    control = SimpleNamespace(
        desired_battery_export_power_kw=desired,
        commands_permitted=authorised,
        desired_work_mode="Force Discharge",
        blocked_reason=None,
    )
    state = {
        "rolling_export_plan": {
            "available": True,
            "current_battery_export_target_kw": requested,
        }
    }
    guard = {"requested_export_kw": requested, "permitted_export_kw": permitted}
    result = audit.agile_current_export_execution_observation(
        snapshot=snapshot, control=control, agile_state=state, physical_guard=guard
    )
    assert result["status"] == status
    assert result["reporting_only"] is True
    assert result["physical_dispatch_verified"] is False
    assert control.desired_battery_export_power_kw == desired
    assert snapshot.battery_soc == 29.0


def test_missing_observations_do_not_claim_success_or_failing_hardware() -> None:
    state = {
        "rolling_export_plan": {
            "available": True,
            "current_battery_export_target_kw": 4.0,
        }
    }
    control = SimpleNamespace(
        desired_battery_export_power_kw=4.0, commands_permitted=True
    )
    snap = SimpleNamespace(grid_export_kw=None, grid_import_kw=0.0)
    result = audit.agile_current_export_execution_observation(
        snapshot=snap, control=control, agile_state=state, physical_guard={}
    )
    assert result["status"] == "missing_or_invalid_current_evidence"
    assert result["physical_dispatch_verified"] is False
