"""Read-only attribution of observed history gaps to nearby KEMS updates.

A successful updater transaction near a gap is timing evidence, not proof of
its cause. Neither the underlying saved ledger nor simulation completeness,
supplier-meter data, or any physical KEMS control is modified here.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
MIN_GAP_SECONDS = 600
UPDATE_AFTER_GAP_GRACE = timedelta(minutes=5)
RECENT_DAYS = 14
MAX_DETAIL_ROWS = 40


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def history_gap_provenance(
    *,
    records: Sequence[Any],
    update_history: Sequence[Mapping[str, Any]] | None,
    lifecycle_events: Sequence[Mapping[str, Any]] | None = None,
    ledger_audit: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Summarise real observation gaps and strictly identified update proximity.

    This never transforms an incomplete replay into a complete day. It simply
    distinguishes recorded ledger totals, incomplete simulation coverage and
    candidates for planned KEMS update downtime.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    today = now.astimezone(LONDON).date()
    oldest = today - timedelta(days=RECENT_DAYS - 1)
    updates: list[tuple[datetime, str | None]] = []
    for item in (update_history or [])[-30:]:
        if not isinstance(item, Mapping) or item.get("result") != "success":
            continue
        completed = _instant(item.get("completed_at"))
        if completed is None:
            continue
        target = item.get("target")
        updates.append((completed, str(target) if isinstance(target, str) else None))

    lifecycle: list[tuple[datetime, str]] = []
    for event in lifecycle_events or []:
        if not isinstance(event, Mapping):
            continue
        kind = event.get("kind")
        if kind not in {
            "kems_setup",
            "core_started_event_observed",
            "core_stopping_event_observed",
            "core_restart_service_requested",
        }:
            continue
        stamp = _instant(event.get("observed_at"))
        if stamp is not None:
            lifecycle.append((stamp, kind))

    daily_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "gaps_over_10_minutes": 0,
            "gaps_near_successful_kems_update": 0,
            "gaps_without_update_correspondence": 0,
            "gaps_near_kems_setup": 0,
            "gaps_near_observed_core_lifecycle": 0,
            "gaps_without_any_recorded_lifecycle_or_update": 0,
            "seconds_of_observation_gaps": 0,
        }
    )
    day_stamps: dict[str, list[datetime]] = defaultdict(list)
    for snap in records:
        stamp = _instant(getattr(snap, "timestamp", None))
        if stamp is None or stamp > now.astimezone(UTC):
            continue
        day = stamp.astimezone(LONDON).date()
        if oldest <= day <= today:
            day_stamps[day.isoformat()].append(stamp)

    details: list[dict[str, Any]] = []
    for day_text, stamps in sorted(day_stamps.items()):
        stamps.sort()
        for start, end in zip(stamps, stamps[1:], strict=False):
            seconds = (end - start).total_seconds()
            if seconds <= MIN_GAP_SECONDS:
                continue
            matching = next(
                (
                    target
                    for at, target in updates
                    if start <= at <= end + UPDATE_AFTER_GAP_GRACE
                ),
                None,
            )
            # A successful update with no target still counts as evidence.
            update_near = any(
                start <= at <= end + UPDATE_AFTER_GAP_GRACE for at, _ in updates
            )
            near_events = [
                kind
                for at, kind in lifecycle
                if start - timedelta(minutes=2) <= at <= end + UPDATE_AFTER_GAP_GRACE
            ]
            kems_setup_near = "kems_setup" in near_events
            core_lifecycle_near = any(
                kind
                in {
                    "core_started_event_observed",
                    "core_stopping_event_observed",
                }
                for kind in near_events
            )
            if core_lifecycle_near:
                lifecycle_classification = "core_lifecycle_event_near_gap"
            elif kems_setup_near:
                lifecycle_classification = "kems_setup_near_gap"
            elif update_near:
                lifecycle_classification = "completed_kems_update_near_gap"
            elif "core_restart_service_requested" in near_events:
                lifecycle_classification = "core_restart_request_near_gap"
            else:
                lifecycle_classification = "no_recorded_correspondence"
            counters = daily_counts[day_text]
            counters["gaps_over_10_minutes"] += 1
            counters["gaps_near_kems_setup"] += int(kems_setup_near)
            counters["gaps_near_observed_core_lifecycle"] += int(core_lifecycle_near)
            counters["gaps_without_any_recorded_lifecycle_or_update"] += int(
                lifecycle_classification == "no_recorded_correspondence"
            )
            counters["seconds_of_observation_gaps"] += round(seconds)
            counters[
                (
                    "gaps_near_successful_kems_update"
                    if update_near
                    else "gaps_without_update_correspondence"
                )
            ] += 1
            details.append(
                {
                    "date": day_text,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "gap_seconds": round(seconds),
                    "successfully_completed_kems_update_near_gap": update_near,
                    "nearby_update_version": matching,
                    "update_proximity_is_cause_proof": False,
                    "metered_energy_during_gap": "unknown",
                    "lifecycle_classification": lifecycle_classification,
                    "kems_setup_near_gap": kems_setup_near,
                    "core_lifecycle_event_near_gap": core_lifecycle_near,
                    "restart_service_request_near_gap": (
                        "core_restart_service_requested" in near_events
                    ),
                    "kems_setup_alone_proves_core_restart": False,
                }
            )

    # Rank only gaps lacking *recorded* update or lifecycle correspondence.
    # A missing marker is not proof there was no HA restart: lifecycle capture
    # is prospective, and update history is bounded. Rank existing records,
    # never extrapolate lost energy from gap duration.
    unexplained = sorted(
        (
            item
            for item in details
            if item["lifecycle_classification"] == "no_recorded_correspondence"
        ),
        key=lambda item: (-item["gap_seconds"], item["start"]),
    )
    next_unexplained = [
        {
            "date": item["date"],
            "start": item["start"],
            "end": item["end"],
            "gap_seconds": item["gap_seconds"],
            "recorded_restart_correspondence": False,
            "physical_import_export_kwh": None,
        }
        for item in unexplained[:5]
    ]
    rows: list[dict[str, Any]] = []
    for item in ledger_audit.get("recent_days") or []:
        if not isinstance(item, Mapping):
            continue
        day = item.get("date")
        if not isinstance(day, str):
            continue
        row_counts = daily_counts.get(day, {})
        complete = item.get("simulation_replay_complete") is True
        recorded = item.get("recorded_totals_available") is True
        rows.append(
            {
                "date": day,
                "recorded_totals_available": recorded,
                "simulation_replay_complete": complete,
                "simulation_coverage_percent": item.get(
                    "simulation_data_coverage_percent"
                ),
                "independent_meter_completeness": "not_verified",
                "display_status": (
                    "simulation_replay_complete_meter_not_verified"
                    if complete
                    else (
                        "recorded_totals_available_simulation_partial"
                        if recorded
                        else "no_verified_recorded_totals"
                    )
                ),
                "ongoing_day": day == today.isoformat(),
                "gaps_over_10_minutes": row_counts.get("gaps_over_10_minutes", 0),
                "gaps_near_successful_kems_update": row_counts.get(
                    "gaps_near_successful_kems_update", 0
                ),
                "gaps_without_update_correspondence": row_counts.get(
                    "gaps_without_update_correspondence", 0
                ),
                "restart_cause_proven": False,
                "gaps_near_kems_setup": row_counts.get("gaps_near_kems_setup", 0),
                "gaps_near_observed_core_lifecycle": row_counts.get(
                    "gaps_near_observed_core_lifecycle", 0
                ),
                "gaps_without_any_recorded_lifecycle_or_update": (
                    row_counts.get("gaps_without_any_recorded_lifecycle_or_update", 0)
                ),
            }
        )
    return {
        "scope": "read_only_last_14_days",
        "restart_cause_proven": False,
        "update_proximity_is_not_cause_proof": True,
        "update_history_is_bounded": True,
        "successful_update_events_considered": len(updates),
        "lifecycle_events_considered": len(lifecycle),
        "lifecycle_markers_are_prospective_only": True,
        "kems_setup_is_not_core_restart_proof": True,
        "absence_of_lifecycle_events_does_not_exclude_restart": True,
        "recorded_totals_do_not_prove_full_meter_coverage": True,
        "simulation_completeness_unchanged": True,
        "source_gap_details": details[-MAX_DETAIL_ROWS:],
        "source_gap_details_omitted": max(0, len(details) - MAX_DETAIL_ROWS),
        "gaps_without_recorded_correspondence": len(unexplained),
        "largest_unattributed_observation_gaps": next_unexplained,
        "largest_unattributed_observation_gaps_omitted": max(
            len(unexplained) - len(next_unexplained), 0
        ),
        "unattributed_gap_note": (
            "Prioritised by elapsed time only. Lack of a recorded update or "
            "lifecycle event does not prove no restart; no physical kWh or "
            "recovered financial value can be inferred."
        ),
        "days": rows,
        "next_step": (
            "Correlate observed KEMS setup/Core lifecycle markers with Core "
            "restart logs, and independently confirm cumulative "
            "grid import/export meter anchors to prove missing intervals. "
            "Do not mark replay complete or infer kWh from elapsed downtime."
        ),
    }
