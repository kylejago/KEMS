"""Read-only estimated Octopus Weekend Happy Hour bill credit.

The smart meter's gross billed import is preserved. Octopus credits eligible
import later (16 kWh maximum per independently booked one-hour reward).
This estimate uses the currently observed import unit rate as a proxy: it is
not supplier settlement or a rewrite of historic half-hour tariff charges.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

_LONDON = ZoneInfo("Europe/London")


def _datetime(value: Any) -> datetime | None:
    try:
        timestamp = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return None
    return timestamp if timestamp.tzinfo is not None else None


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if isfinite(number) and number >= 0 else None


def estimate_happy_hour_credit(
    *,
    plan: Mapping[str, Any],
    bookings: Mapping[str, Any],
    now: datetime,
    import_rate_pence: float | None,
    gross_import_cost_pence: float | None,
) -> dict[str, Any]:
    """Estimate only independently booked, continuously metered reward import.

    None means there is no fresh verified estimate, not an assertion of zero
    supplier credit. A previous verified daily estimate can be retained in the
    persisted reporting ledger if the completed event drops out of planning.
    """
    unavailable: dict[str, Any] = {
        "estimated_credit_pence": None,
        "credited_import_kwh": None,
        "supplier_settled": False,
        "rate_basis": "current observed import unit rate (indicative)",
    }
    rate = _positive_number(import_rate_pence)
    gross = _positive_number(gross_import_cost_pence)
    hours = plan.get("reward_hours")
    entries = bookings.get("bookings")
    if (
        rate is None
        or gross is None
        or not isinstance(hours, list)
        or not isinstance(entries, list)
        or not isinstance(now, datetime)
        or now.tzinfo is None
    ):
        return unavailable

    # A published/available event alone is not authority for free power.
    # Only individually confirmed joined bookings count.
    confirmed: set[tuple[datetime, datetime]] = set()
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        start, end = _datetime(item.get("start")), _datetime(item.get("end"))
        if (
            start is not None
            and end is not None
            and start < end
            and (end - start).total_seconds() <= 3600
            and (item.get("event_id") or item.get("event_code"))
        ):
            confirmed.add((start, end))

    if not confirmed:
        return unavailable

    day = now.astimezone(_LONDON).date()
    counted: set[tuple[datetime, datetime]] = set()
    energy = 0.0
    for hour in hours:
        if not isinstance(hour, Mapping) or hour.get("coverage_complete") is not True:
            continue
        start, end = _datetime(hour.get("start")), _datetime(hour.get("end"))
        if (
            start is None
            or end is None
            or (start, end) not in confirmed
            or (start, end) in counted
            or start.astimezone(_LONDON).date() != day
            or start > now
        ):
            continue
        measured = _positive_number(hour.get("import_kwh"))
        cap = _positive_number(hour.get("cap_kwh"))
        if measured is None or cap is None:
            continue
        counted.add((start, end))
        energy += min(measured, cap, 16.0)

    if not counted:
        return unavailable
    return {
        "estimated_credit_pence": round(min(energy * rate, gross), 3),
        "credited_import_kwh": round(energy, 3),
        "supplier_settled": False,
        "rate_basis": "current observed import unit rate (indicative)",
        "verified_reward_hours": len(counted),
    }
