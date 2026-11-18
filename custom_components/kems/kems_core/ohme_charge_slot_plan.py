"""Read-only normalisation of official Ohme charge-slot action responses.

The Ohme plan is *charger intent*, NOT Octopus supplier discount authority.
No function in this module grants a cheap period, inverter mode, tariff rate,
EV export block, or battery charge command.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

MAX_RETURNED_SLOTS = 32
MAX_DURATION = timedelta(hours=24)
MAX_FUTURE = timedelta(hours=48)


def _timestamp(value: Any, local_zone: ZoneInfo) -> tuple[datetime | None, bool]:
    """Parse official dated timestamps; never guess dates from HH:MM ranges."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None, False
    else:
        return None, False
    assumed_local = parsed.tzinfo is None
    if assumed_local:
        parsed = parsed.replace(tzinfo=local_zone)
    return parsed.astimezone(UTC), assumed_local


def _nonnegative_number(value: Any, maximum: float) -> float | None:
    """Treat non-finite, boolean and out-of-range device fields as unknown."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(number) or number < 0 or number > maximum:
        return None
    return number


def observe_ohme_slot_response(
    response: Any,
    *,
    now: datetime,
    timezone: str = "Europe/London",
) -> dict[str, Any]:
    """Normalise response slots with evidence labels and overlap/age checks.

    Slots may include already-expired historical legs or revised overlapping
    sub-slots; do not infer current charging or billing from those records.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone aware")
    try:
        zone = ZoneInfo(timezone)
    except (KeyError, ValueError):
        zone = ZoneInfo("Europe/London")
    reference = now.astimezone(UTC)
    if not isinstance(response, Mapping) or not isinstance(response.get("slots"), list):
        return {
            "status": "unexpected_response",
            "slots": [],
            "raw_count": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "expired_count": 0,
            "active_count": 0,
            "overlap_count": 0,
            "duplicate_count": 0,
            "naive_timestamps_assumed_local": 0,
            "discount_authority": False,
        }

    rows: list[tuple[datetime, datetime, float | None, float | None]] = []
    invalid = 0
    naive_count = 0
    for item in response["slots"][:128]:
        if not isinstance(item, Mapping):
            invalid += 1
            continue
        start, start_naive = _timestamp(item.get("start"), zone)
        end, end_naive = _timestamp(item.get("end"), zone)
        if (
            start is None
            or end is None
            or end <= start
            or end - start > MAX_DURATION
            or start > reference + MAX_FUTURE
        ):
            invalid += 1
            continue
        naive_count += int(start_naive or end_naive)
        power = _nonnegative_number(item.get("power"), 22000.0)
        energy = _nonnegative_number(item.get("energy"), 500000.0)
        rows.append((start, end, power, energy))

    rows.sort(key=lambda entry: (entry[0], entry[1], entry[2] or 0))
    unique = list(dict.fromkeys(rows))
    duplicates = len(rows) - len(unique)
    overlaps = sum(
        int(current[0] < previous[1])
        for previous, current in zip(unique, unique[1:])
    )
    active_count = sum(start <= reference < end for start, end, _, _ in unique)
    expired_count = sum(end <= reference for _, end, _, _ in unique)
    normalized = [
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "power_kw": round(power / 1000, 3) if power is not None else None,
            "energy_kwh": round(energy / 1000, 3) if energy is not None else None,
            "active_at_observation": start <= reference < end,
            "expired_at_observation": end <= reference,
        }
        for start, end, power, energy in unique[:MAX_RETURNED_SLOTS]
    ]
    return {
        "status": "plan_observed" if normalized else "no_slots_reported",
        "slots": normalized,
        "raw_count": len(response["slots"]),
        "valid_count": len(unique),
        "invalid_count": invalid + max(len(response["slots"]) - 128, 0),
        "expired_count": expired_count,
        "active_count": active_count,
        "overlap_count": overlaps,
        "duplicate_count": duplicates,
        "naive_timestamps_assumed_local": naive_count,
        "truncated": len(unique) > MAX_RETURNED_SLOTS,
        "discount_authority": False,
    }
