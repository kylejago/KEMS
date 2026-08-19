"""Pure helpers for Agile Smart Export price-horizon completeness."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp and normalise it to UTC."""
    if value in (None, ""):
        return None
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def expected_slots_for_day(day: date, timezone: ZoneInfo) -> list[dict[str, str]]:
    """Return every real half-hour settlement slot in one local day."""
    start = datetime.combine(day, time.min, tzinfo=timezone).astimezone(UTC)
    end = datetime.combine(
        day + timedelta(days=1),
        time.min,
        tzinfo=timezone,
    ).astimezone(UTC)
    slots: list[dict[str, str]] = []
    cursor = start
    while cursor < end:
        local = cursor.astimezone(timezone)
        slots.append(
            {
                "valid_from": cursor.isoformat(),
                "valid_to": (cursor + timedelta(minutes=30)).isoformat(),
                "local_from": local.isoformat(),
                "label": local.strftime("%H:%M"),
                "timezone": local.tzname() or "",
            }
        )
        cursor += timedelta(minutes=30)
    return slots


def missing_slots_for_day(
    slots: list[dict[str, Any]],
    day: date,
    timezone: ZoneInfo,
) -> list[dict[str, str]]:
    """Return expected local-day slots that are not present in the price payload."""
    known = {
        parsed
        for item in slots
        if isinstance(item, dict)
        and (parsed := _parse_timestamp(item.get("valid_from"))) is not None
    }
    return [
        item
        for item in expected_slots_for_day(day, timezone)
        if _parse_timestamp(item["valid_from"]) not in known
    ]


def remaining_price_horizon(
    slots: list[dict[str, Any]],
    *,
    now: datetime,
    deadline: datetime,
    timezone: ZoneInfo,
) -> dict[str, Any]:
    """Measure known prices for every remaining slot before a discharge deadline."""
    now_utc = now.astimezone(UTC)
    deadline_utc = deadline.astimezone(UTC)
    if deadline_utc <= now_utc:
        return {
            "complete": True,
            "expected_count": 0,
            "known_count": 0,
            "missing_count": 0,
            "missing_slots": [],
            "current_slot_known": False,
        }

    known = {
        parsed
        for item in slots
        if isinstance(item, dict)
        and (parsed := _parse_timestamp(item.get("valid_from"))) is not None
    }

    expected: list[dict[str, str]] = []
    day = now.astimezone(timezone).date()
    last_day = deadline.astimezone(timezone).date()
    while day <= last_day:
        for item in expected_slots_for_day(day, timezone):
            start = _parse_timestamp(item["valid_from"])
            end = _parse_timestamp(item["valid_to"])
            if start is None or end is None:
                continue
            if end > now_utc and start < deadline_utc:
                expected.append(item)
        day += timedelta(days=1)

    missing = [
        item
        for item in expected
        if _parse_timestamp(item["valid_from"]) not in known
    ]
    current_known = any(
        (start := _parse_timestamp(item.get("valid_from"))) is not None
        and (end := _parse_timestamp(item.get("valid_to"))) is not None
        and start <= now_utc < end
        for item in slots
        if isinstance(item, dict)
    )
    return {
        "complete": not missing,
        "expected_count": len(expected),
        "known_count": len(expected) - len(missing),
        "missing_count": len(missing),
        "missing_slots": missing,
        "current_slot_known": current_known,
    }
