"""Display-only EV SOC precedence; never affects charging or Ohme writes."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any


def _soc(value: Any) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if isfinite(result) and 0 <= result <= 100 else None


def displayed_ev_soc(
    vehicle_state: Any,
    ohme_soc: Any,
    *,
    now: datetime,
    max_vehicle_age_seconds: float = 21600,
) -> dict[str, Any]:
    """Prefer a recently reported vehicle SOC; else retain the Ohme display.

    The vehicle state must be from the configured independent vehicle source.
    This function has no ability to change a Snapshot, EV control, or Ohme.
    """
    source_value = _soc(getattr(vehicle_state, "state", None))
    reported_at = getattr(vehicle_state, "last_reported", None) or getattr(
        vehicle_state, "last_updated", None
    )
    age = None
    if isinstance(reported_at, datetime) and reported_at.tzinfo and now.tzinfo:
        age = (now - reported_at).total_seconds()
    if (
        source_value is not None
        and age is not None
        and 0 <= age <= max_vehicle_age_seconds
    ):
        return {
            "value": source_value,
            "source": "vehicle",
            "age_seconds": round(age, 1),
        }
    return {
        "value": _soc(ohme_soc),
        "source": "ohme" if _soc(ohme_soc) is not None else "unavailable",
        "age_seconds": round(age, 1) if age is not None else None,
    }
