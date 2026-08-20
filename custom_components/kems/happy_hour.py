"""Manual Octopus Weekend Happy Hour configuration helpers.

Octopus does not currently expose the customer's chosen Weekend Happy Hour
through the Home Assistant integration used by KEMS.  Alpha7.43 therefore keeps
this input deliberately small and local: the user can enable planning, choose a
start date/time and choose one or two booked hours.  The optimiser consumes the
same event shape regardless of source so a future Octopus provider can replace
the manual source without changing dispatch policy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

CONF_HAPPY_HOUR_ENABLED = "weekend_happy_hour_enabled"
CONF_HAPPY_HOUR_START = "weekend_happy_hour_start"
CONF_HAPPY_HOUR_DURATION_HOURS = "weekend_happy_hour_duration_hours"

DEFAULT_HAPPY_HOUR_DURATION_HOURS = 1
HAPPY_HOUR_FAIR_USE_KWH_PER_REWARD = 16.0


def parse_happy_hour_start(value: Any) -> datetime | None:
    """Return one timezone-aware Happy Hour start timestamp when configured."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def happy_hour_duration_hours(options: Mapping[str, Any]) -> int:
    """Return the booked duration, constrained to Octopus' one/two-hour UI."""
    try:
        value = int(options.get(CONF_HAPPY_HOUR_DURATION_HOURS, 1))
    except (TypeError, ValueError):
        value = DEFAULT_HAPPY_HOUR_DURATION_HOURS
    return 2 if value >= 2 else 1


def happy_hour_fair_use_cap_kwh(options: Mapping[str, Any]) -> float:
    """Return the total cap for the number of booked one-hour rewards.

    Octopus defines one Weekend Happy Hour reward as one free hour capped at
    16 kWh and allows two rewards to be selected together.  KEMS therefore
    treats a two-hour booking as two one-hour rewards for planning evidence.
    """
    return HAPPY_HOUR_FAIR_USE_KWH_PER_REWARD * happy_hour_duration_hours(options)


def manual_happy_hour_event(options: Mapping[str, Any]) -> dict[str, Any]:
    """Return the source-neutral manual event payload used by Agile planning."""
    enabled = bool(options.get(CONF_HAPPY_HOUR_ENABLED, False))
    start = parse_happy_hour_start(options.get(CONF_HAPPY_HOUR_START))
    duration = happy_hour_duration_hours(options)
    end = start + timedelta(hours=duration) if start is not None else None
    return {
        "enabled": enabled,
        "source": "manual",
        "start": start,
        "end": end,
        "duration_hours": duration,
        "fair_use_cap_kwh": happy_hour_fair_use_cap_kwh(options),
    }
