"""Read-only observation-gap evidence for KEMS historical completeness.

This is diagnostic data only: it does not determine recorded ledger completion,
settled financial amounts, simulation outputs or physical dispatch.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .simulation import _load_kw

LONDON = ZoneInfo("Europe/London")
LARGE_GAP_SECONDS = 600


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
            "gaps_over_10_minutes": 0,
            "largest_gap_seconds": 0,
            "gap_seconds_over_10_minutes": 0,
        }
        for current, following in zip(values, values[1:], strict=False):
            elapsed = (following.timestamp - current.timestamp).total_seconds()
            if elapsed <= 0:
                continue
            result["pair_count"] += 1
            if elapsed > LARGE_GAP_SECONDS:
                result["gaps_over_10_minutes"] += 1
                result["gap_seconds_over_10_minutes"] += round(elapsed)
            result["largest_gap_seconds"] = max(
                result["largest_gap_seconds"], round(elapsed)
            )
            if _load_kw(following) is None:
                result["missing_following_load_pairs"] += 1
            elif (
                getattr(current, "current_import_rate", None) is None
                or "current_import_rate"
                in getattr(current, "tariff_stale_fields", ())
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
        daily.append(result)

    return {
        "scope": "read_only_recent_snapshot_pairs",
        "days_with_records": len(daily),
        "days_requested": recent_days,
        "time_basis": "Europe/London",
        "simulation_source_checks_only": True,
        "gap_duration_is_not_metered_kwh": True,
        "not_authoritative_for_period_completion": True,
        "not_supplier_settlement": True,
        "intervals_count_pairs_not_elapsed_hours": True,
        "day_rows": daily,
    }
