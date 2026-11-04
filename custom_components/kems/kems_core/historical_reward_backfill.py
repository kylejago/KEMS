"""Read-only historical Happy Hour observations, never booking/control authority.

Five-minute KEMS snapshots can support a *provisional* credit for witnessed
intervals of an independently joined Octopus reward hour. Missing intervals or
missing historical prices remain uncredited. This does not change metered costs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from math import isfinite
from typing import Any

from .roi_provisional_happy_hour import estimate_partial_reward_hours


def _nonnegative(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) and parsed >= 0 else None


def historical_import_readings(
    records: Iterable[Any], windows: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Extract only retained physical readings with their contemporaneous rate.

    No modern tariff substitution or interpolation. KEMS history has a
    five-minute cadence; its physical grid-import readings are observations,
    not independently confirmed smart-meter interval settlement.
    """
    boundaries: list[tuple[datetime, datetime]] = []
    for window in windows:
        if not isinstance(window, Mapping):
            continue
        try:
            start = datetime.fromisoformat(str(window["start"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(window["end"]).replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            continue
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or not 55 <= (end - start).total_seconds() / 60 <= 65
        ):
            continue
        boundaries.append((start, end))
    if not boundaries:
        return []
    earliest = min(start for start, _ in boundaries)
    latest = max(end for _, end in boundaries)
    readings: list[dict[str, Any]] = []
    for record in records:
        at = getattr(record, "timestamp", None)
        if (
            not isinstance(at, datetime)
            or at.tzinfo is None
            or not earliest <= at <= latest
        ):
            continue
        if not any(start <= at <= end for start, end in boundaries):
            continue
        stale = getattr(record, "stale_fields", ()) or ()
        tariff_stale = getattr(record, "tariff_stale_fields", ()) or ()
        if "grid_import_kw" in stale or "current_import_rate" in tariff_stale:
            continue
        kw = _nonnegative(getattr(record, "grid_import_kw", None))
        rate = _nonnegative(getattr(record, "current_import_rate", None))
        if kw is None or kw > 30 or rate is None or rate > 200:
            continue
        readings.append(
            {
                "timestamp": at,
                "grid_import_kw": kw,
                "import_rate_pence": rate,
            }
        )
    return readings


def estimate_historical_happy_hour_credits(
    *,
    confirmed_bookings: Iterable[Mapping[str, Any]],
    history: Iterable[Any],
    completed_receipts: Iterable[Mapping[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    """Use retained five-minute evidence for commissioned, joined hours only."""
    windows = list(confirmed_bookings)
    readings = historical_import_readings(history, windows)
    return estimate_partial_reward_hours(
        windows=windows,
        readings=readings,
        completed_receipts=completed_receipts,
        now=now,
        max_sample_gap_seconds=390,
        historical_sampled=True,
    )
