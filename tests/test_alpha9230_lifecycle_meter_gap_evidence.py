"""Read-only restart attribution and import/export gap-anchor regression cases."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from kems_core.history_gap_provenance import history_gap_provenance
from kems_core.meter_gap_anchor_evidence import meter_gap_anchor_evidence


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _records() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(timestamp=_dt("2026-11-18T21:26:00")),
        SimpleNamespace(timestamp=_dt("2026-11-18T21:42:00")),
    ]


def _report(events: list[dict]) -> dict:
    return history_gap_provenance(
        records=_records(),
        update_history=[],
        lifecycle_events=events,
        ledger_audit={
            "recent_days": [
                {
                    "date": "2026-11-18",
                    "recorded_totals_available": True,
                    "simulation_replay_complete": False,
                }
            ]
        },
        now=_dt("2026-11-18T22:00:00"),
    )


def test_kems_setup_near_unlogged_manual_install_does_not_prove_restart() -> None:
    report = _report(
        [
            {
                "kind": "kems_setup",
                "observed_at": "2026-11-18T21:42:15+00:00",
            }
        ]
    )
    gap = report["source_gap_details"][0]
    assert gap["lifecycle_classification"] == "kems_setup_near_gap"
    assert gap["kems_setup_alone_proves_core_restart"] is False
    assert gap["metered_energy_during_gap"] == "unknown"
    assert report["days"][0]["gaps_near_kems_setup"] == 1
    assert report["days"][0]["gaps_without_update_correspondence"] == 1
    assert report["days"][0]["simulation_replay_complete"] is False


def test_core_stop_and_start_are_observed_even_without_updater_record() -> None:
    report = _report(
        [
            {
                "kind": "core_stopping_event_observed",
                "observed_at": "2026-11-18T21:27:00+00:00",
            },
            {
                "kind": "core_started_event_observed",
                "observed_at": "2026-11-18T21:41:50+00:00",
            },
        ]
    )
    gap = report["source_gap_details"][0]
    assert gap["lifecycle_classification"] == "core_lifecycle_event_near_gap"
    assert gap["core_lifecycle_event_near_gap"] is True
    assert gap["update_proximity_is_cause_proof"] is False
    assert report["days"][0]["gaps_near_observed_core_lifecycle"] == 1
    assert report["days"][0]["restart_cause_proven"] is False


def test_no_lifecycle_evidence_is_not_proof_no_restart() -> None:
    report = _report(
        [
            {
                "kind": "kems_setup",
                "observed_at": "2026-11-18T19:00:00+00:00",
            }
        ]
    )
    assert report["days"][0]["gaps_without_any_recorded_lifecycle_or_update"] == 1
    assert report["absence_of_lifecycle_events_does_not_exclude_restart"] is True


def _counter(at: str, kwh: float) -> dict:
    return {"reported_at": at, "kwh": kwh}


def test_two_way_counter_anchors_are_observation_only() -> None:
    result = meter_gap_anchor_evidence(
        gaps=[
            {
                "start": "2026-11-18T21:26:00+00:00",
                "end": "2026-11-18T21:42:00+00:00",
            }
        ],
        import_lifetime_rows=[
            _counter("2026-11-18T21:21:00+00:00", 100.0),
            _counter("2026-11-18T21:46:00+00:00", 101.0),
        ],
        export_lifetime_rows=[
            _counter("2026-11-18T21:20:00+00:00", 220.0),
            _counter("2026-11-18T21:45:00+00:00", 220.5),
        ],
    )
    gap = result["gap_rows"][0]
    assert gap["import_counter"]["status"] == "plausible_counter_pair_unverified"
    assert gap["export_counter"]["status"] == "plausible_counter_pair_unverified"
    assert gap["import_counter"]["delta_candidate_kwh"] == 1.0
    assert gap["exact_unobserved_interval_kwh"] is None
    assert gap["eligible_for_energy_cost_or_reward_backfill"] is False
    assert result["backfill_approved"] is False


def test_missing_export_anchor_prevents_two_way_claim() -> None:
    result = meter_gap_anchor_evidence(
        gaps=[
            {
                "start": "2026-11-18T21:26:00+00:00",
                "end": "2026-11-18T21:42:00+00:00",
            }
        ],
        import_lifetime_rows=[
            _counter("2026-11-18T21:21:00+00:00", 100.0),
            _counter("2026-11-18T21:46:00+00:00", 101.0),
        ],
        export_lifetime_rows=[],
    )
    assert (
        result["gap_rows"][0]["export_counter"]["status"] == "no_bounded_anchor_pair"
    )
    assert result["two_way_physical_provenance_verified"] is False


def test_counter_resets_and_large_changes_not_plausible() -> None:
    gap = [
        {
            "start": "2026-11-18T21:26:00+00:00",
            "end": "2026-11-18T21:42:00+00:00",
        }
    ]
    result = meter_gap_anchor_evidence(
        gaps=gap,
        import_lifetime_rows=[
            _counter("2026-11-18T21:25:00+00:00", 105.0),
            _counter("2026-11-18T21:43:00+00:00", 5.0),
        ],
        export_lifetime_rows=[
            _counter("2026-11-18T21:25:00+00:00", 5.0),
            _counter("2026-11-18T21:43:00+00:00", 40.0),
        ],
    )
    entry = result["gap_rows"][0]
    assert entry["import_counter"]["status"] == "reset_or_nonmonotonic"
    assert entry["export_counter"]["status"] == "implausible_change"
    assert result["changes_to_cost_roi_dispatch"] is False
