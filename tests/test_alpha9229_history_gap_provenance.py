"""Regression tests for read-only restart-gap versus saved-ledger reporting."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

from kems_core.history_gap_provenance import history_gap_provenance


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def _snap(text: str) -> SimpleNamespace:
    return SimpleNamespace(timestamp=_instant(text))


def _audit(*, complete: bool = False, totals: bool = True) -> dict:
    return {
        "recent_days": [
            {
                "date": "2026-11-18",
                "simulation_replay_complete": complete,
                "recorded_totals_available": totals,
                "simulation_data_coverage_percent": 95.5,
            }
        ]
    }


def test_successful_update_near_gap_is_timing_evidence_not_completion() -> None:
    records = [
        _snap("2026-11-18T05:46:35"),
        _snap("2026-11-18T06:04:22"),
        _snap("2026-11-18T06:09:22"),
    ]
    history = [
        {
            "result": "success",
            "completed_at": "2026-11-18T06:05:30+00:00",
            "target": "0.9.0-alpha9.227",
        }
    ]
    saved = _audit()
    previous_saved = deepcopy(saved)
    report = history_gap_provenance(
        records=records,
        update_history=history,
        ledger_audit=saved,
        now=_instant("2026-11-18T21:00:00"),
    )
    day = report["days"][0]
    assert day["simulation_replay_complete"] is False
    assert day["recorded_totals_available"] is True
    assert day["display_status"] == "recorded_totals_available_simulation_partial"
    assert day["gaps_near_successful_kems_update"] == 1
    assert day["gaps_without_update_correspondence"] == 0
    assert day["ongoing_day"] is True
    assert report["source_gap_details"][0]["gap_seconds"] == 1067
    assert report["source_gap_details"][0]["nearby_update_version"] == (
        "0.9.0-alpha9.227"
    )
    assert report["source_gap_details"][0]["metered_energy_during_gap"] == "unknown"
    assert report["simulation_completeness_unchanged"] is True
    assert report["restart_cause_proven"] is False
    assert saved == previous_saved


def test_other_gaps_cannot_be_excused_by_unrelated_updates() -> None:
    records = [
        _snap("2026-11-18T20:20:52"),
        _snap("2026-11-18T20:35:44"),
    ]
    history = [
        {
            "result": "success",
            "completed_at": "2026-11-18T18:00:00+00:00",
        },
        {
            "result": "failed",
            "completed_at": "2026-11-18T20:30:00+00:00",
        },
        {
            "result": "success",
            "completed_at": "2026-11-18T20:47:00+00:00",
        },
    ]
    report = history_gap_provenance(
        records=records,
        update_history=history,
        ledger_audit=_audit(),
        now=_instant("2026-11-18T21:00:00"),
    )
    day = report["days"][0]
    assert day["gaps_near_successful_kems_update"] == 0
    assert day["gaps_without_update_correspondence"] == 1
    assert report["successful_update_events_considered"] == 2
    assert (
        report["source_gap_details"][0]["successfully_completed_kems_update_near_gap"]
        is False
    )


def test_no_meter_completion_inferred_from_good_simulation() -> None:
    report = history_gap_provenance(
        records=[],
        update_history=None,
        ledger_audit=_audit(complete=True),
        now=_instant("2026-11-18T21:00:00"),
    )
    day = report["days"][0]
    assert day["display_status"] == "simulation_replay_complete_meter_not_verified"
    assert day["independent_meter_completeness"] == "not_verified"
    assert report["recorded_totals_do_not_prove_full_meter_coverage"] is True


def test_unknown_old_coverage_stays_unknown_and_no_totals_are_invented() -> None:
    report = history_gap_provenance(
        records=[_snap("2026-11-18T06:00:00")],
        update_history=[{"result": "success", "completed_at": "unavailable"}],
        ledger_audit=_audit(totals=False),
        now=_instant("2026-11-18T21:00:00"),
    )
    day = report["days"][0]
    assert day["display_status"] == "no_verified_recorded_totals"
    assert report["successful_update_events_considered"] == 0
    assert not report["source_gap_details"]


def test_naive_update_time_not_accepted_as_evidence() -> None:
    report = history_gap_provenance(
        records=[
            _snap("2026-11-18T06:00:00"),
            _snap("2026-11-18T06:20:00"),
        ],
        update_history=[{"result": "success", "completed_at": "2026-11-18T06:10:00"}],
        ledger_audit=_audit(),
        now=_instant("2026-11-18T21:00:00"),
    )
    assert report["days"][0]["gaps_without_update_correspondence"] == 1
