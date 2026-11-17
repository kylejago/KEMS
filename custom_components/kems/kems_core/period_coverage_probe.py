"""Read-only observation-gap evidence for KEMS historical completeness.

This is diagnostic data only: it does not determine recorded ledger completion,
settled financial amounts, simulation outputs or physical dispatch.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from .simulation import _load_kw

LONDON = ZoneInfo("Europe/London")
LARGE_GAP_SECONDS = 600
MAX_GAP_DETAIL_EVENTS = 48


def _independent_grid_sample(snapshot: Any, field: str) -> bool:
    """Require a finite physical grid sample not flagged stale."""
    value = getattr(snapshot, field, None)
    return (
        isinstance(value, (int, float))
        and isfinite(value)
        and value >= 0
        and field not in getattr(snapshot, "stale_fields", ())
    )


def observation_coverage_probe(
    records: list[Any],
    now: datetime,
    *,
    recent_days: int = 14,
) -> dict[str, Any]:
    """Audit recent observation pairs using the simulation's source checks.

    A pair with missing load or import tariff cannot contribute to the
    simulation's covered interval count. An otherwise covered pair may still
    lack independent grid-meter readings, so its simulated "actual" kWh may
    include a load/solar fallback; never label it supplier-verified.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local_today = now.astimezone(LONDON).date()
    lower_day = local_today - timedelta(days=recent_days - 1)
    grouped: dict[str, list[Any]] = {}
    for snapshot in records:
        timestamp = getattr(snapshot, "timestamp", None)
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            continue
        day = timestamp.astimezone(LONDON).date()
        if lower_day <= day <= local_today:
            grouped.setdefault(day.isoformat(), []).append(snapshot)

    daily: list[dict[str, Any]] = []
    # Retain bounded forensic timestamps, not reconstructed interval energy.
    detail_events: list[dict[str, Any]] = []
    reason_count = 0
    for day, values in sorted(grouped.items()):
        values.sort(key=lambda snap: snap.timestamp)
        result: dict[str, Any] = {
            "date": day,
            "observations": len(values),
            "first_observation": values[0].timestamp.isoformat(),
            "last_observation": values[-1].timestamp.isoformat(),
            "pair_count": 0,
            "simulation_replay_eligible_pairs": 0,
            "missing_following_load_pairs": 0,
            "missing_current_load_pairs": 0,
            "missing_or_stale_import_tariff_pairs": 0,
            "eligible_pairs_without_independent_grid_import": 0,
            "eligible_pairs_without_independent_grid_export": 0,
            "independent_grid_import_observed_pairs": 0,
            "independent_grid_export_observed_pairs": 0,
            "independent_grid_both_observed_pairs": 0,
            "gaps_over_10_minutes": 0,
            "largest_gap_seconds": 0,
            "gap_seconds_over_10_minutes": 0,
        }
        for current, following in zip(values, values[1:], strict=False):
            elapsed = (following.timestamp - current.timestamp).total_seconds()
            if elapsed <= 0:
                continue
            result["pair_count"] += 1
            reasons: list[str] = []
            if elapsed > LARGE_GAP_SECONDS:
                reasons.append("observation_gap_over_10_minutes")
            if _load_kw(following) is None:
                reasons.append("missing_following_load")
            if _load_kw(current) is None:
                reasons.append("missing_current_load")
            if (
                getattr(current, "current_import_rate", None) is None
                or "current_import_rate"
                in getattr(current, "tariff_stale_fields", ())
            ):
                reasons.append("missing_or_stale_import_tariff")
            # This deliberately checks physical grid observations even when
            # house-load or import-tariff evidence prevents simulation replay.
            import_evidence = all(
                _independent_grid_sample(snap, "grid_import_kw")
                for snap in (current, following)
            )
            export_evidence = all(
                _independent_grid_sample(snap, "grid_export_kw")
                for snap in (current, following)
            )
            result["independent_grid_import_observed_pairs"] += int(import_evidence)
            result["independent_grid_export_observed_pairs"] += int(export_evidence)
            result["independent_grid_both_observed_pairs"] += int(
                import_evidence and export_evidence
            )
            if not import_evidence:
                reasons.append("independent_import_power_unavailable")
            if not export_evidence:
                reasons.append("independent_export_power_unavailable")
            if reasons:
                reason_count += 1
                detail_events.append(
                    {
                        "date": day,
                        "start": current.timestamp.isoformat(),
                        "end": following.timestamp.isoformat(),
                        "duration_seconds": round(elapsed),
                        "reasons": reasons,
                        "independent_import_power_at_both_ends": import_evidence,
                        "independent_export_power_at_both_ends": export_evidence,
                        "interval_kwh_proven": False,
                        "eligible_for_backfill": False,
                    }
                )
            if elapsed > LARGE_GAP_SECONDS:
                result["gaps_over_10_minutes"] += 1
                result["gap_seconds_over_10_minutes"] += round(elapsed)
            result["largest_gap_seconds"] = max(
                result["largest_gap_seconds"], round(elapsed)
            )
            if _load_kw(following) is None:
                result["missing_following_load_pairs"] += 1
            elif getattr(
                current, "current_import_rate", None
            ) is None or "current_import_rate" in getattr(
                current, "tariff_stale_fields", ()
            ):
                result["missing_or_stale_import_tariff_pairs"] += 1
            elif _load_kw(current) is None:
                result["missing_current_load_pairs"] += 1
            else:
                result["simulation_replay_eligible_pairs"] += 1
                source_stale = getattr(current, "stale_fields", ())
                if (
                    getattr(current, "grid_import_kw", None) is None
                    or "grid_import_kw" in source_stale
                ):
                    result["eligible_pairs_without_independent_grid_import"] += 1
                if (
                    getattr(current, "grid_export_kw", None) is None
                    or "grid_export_kw" in source_stale
                ):
                    result["eligible_pairs_without_independent_grid_export"] += 1
        total = result["pair_count"]
        result["source_eligible_pair_percent"] = (
            round(100 * result["simulation_replay_eligible_pairs"] / total, 2)
            if total
            else None
        )
        result["independent_grid_observed_pair_percent"] = (
            round(100 * result["independent_grid_both_observed_pairs"] / total, 2)
            if total
            else None
        )
        result["independent_meter_completeness"] = "not_verified"
        daily.append(result)

    return {
        "scope": "read_only_recent_snapshot_pairs",
        "days_with_records": len(daily),
        "days_requested": recent_days,
        "time_basis": "Europe/London",
        "simulation_source_checks_only": False,
        "simulation_source_checks_and_independent_grid_observations": True,
        "independent_meter_observation_does_not_prove_full_day": True,
        "gap_duration_is_not_metered_kwh": True,
        "not_authoritative_for_period_completion": True,
        "not_supplier_settlement": True,
        "intervals_count_pairs_not_elapsed_hours": True,
        "day_rows": daily,
        "source_gap_details": detail_events[-MAX_GAP_DETAIL_EVENTS:],
        "source_gap_details_available": reason_count,
        "source_gap_details_omitted": max(
            reason_count - MAX_GAP_DETAIL_EVENTS, 0
        ),
        "source_gap_detail_maximum": MAX_GAP_DETAIL_EVENTS,
        "gap_timestamps_are_not_cumulative_meter_anchors": True,
    }
