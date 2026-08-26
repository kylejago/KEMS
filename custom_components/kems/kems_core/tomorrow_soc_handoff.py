"""Pure Tomorrow SOC continuity helpers.

Tomorrow projections must start from the battery state that can physically exist
at local midnight, not from the SOC observed when the dashboard is viewed.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def _in_window(value: time, start: time, end: time) -> bool:
    """Return whether a local clock time is inside a possibly wrapping window."""
    if start <= end:
        return start <= value < end
    return value >= start or value < end


def _finite_float(value: Any) -> float | None:
    """Return a finite float-like value, or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def project_tomorrow_midnight_soc(
    *,
    now: datetime,
    current_soc_percent: float,
    projected_precheap_soc_percent: float | None,
    battery_capacity_kwh: float,
    max_charge_kw: float,
    charge_efficiency: float,
    offpeak_start: time,
    offpeak_end: time,
) -> tuple[float, dict[str, Any]]:
    """Project SOC at local midnight through the pre-midnight cheap slice.

    Before the cheap period starts, the projected SOC at that boundary is the
    authoritative handoff source. Once cheap charging has started, current SOC
    is authoritative so elapsed cheap time is never charged twice.
    """
    local_now = now.astimezone(LONDON)
    midnight = datetime.combine(
        local_now.date() + timedelta(days=1),
        time.min,
        tzinfo=LONDON,
    )
    current_soc = min(max(float(current_soc_percent), 0.0), 100.0)

    before_midnight = (midnight - timedelta(seconds=1)).time()
    if not _in_window(before_midnight, offpeak_start, offpeak_end):
        return current_soc, {
            "active": False,
            "basis": "no pre-midnight cheap window",
            "current_soc_percent": round(current_soc, 3),
            "midnight_soc_percent": round(current_soc, 3),
            "hardware_writes": "blocked",
        }

    cheap_start = datetime.combine(
        local_now.date(),
        offpeak_start,
        tzinfo=LONDON,
    )
    if cheap_start >= midnight:
        return current_soc, {
            "active": False,
            "basis": "cheap window does not precede midnight",
            "current_soc_percent": round(current_soc, 3),
            "midnight_soc_percent": round(current_soc, 3),
            "hardware_writes": "blocked",
        }

    projected_precheap = _finite_float(projected_precheap_soc_percent)
    if local_now < cheap_start:
        start_soc = (
            min(max(projected_precheap, 0.0), 100.0)
            if projected_precheap is not None
            else current_soc
        )
        charge_from = cheap_start
        basis = (
            "forecast projected SOC at cheap start"
            if projected_precheap is not None
            else "current SOC fallback at cheap start"
        )
    elif local_now < midnight:
        start_soc = current_soc
        charge_from = local_now
        basis = "current SOC inside active cheap window"
    else:
        start_soc = current_soc
        charge_from = midnight
        basis = "current SOC at/after midnight"

    hours = max((midnight - charge_from).total_seconds() / 3600.0, 0.0)
    capacity = max(float(battery_capacity_kwh), 0.1)
    efficiency = min(max(float(charge_efficiency), 0.01), 1.0)
    charge_kw = max(float(max_charge_kw), 0.0)
    stored_needed_kwh = max((100.0 - start_soc) * capacity / 100.0, 0.0)
    max_input_kwh = charge_kw * hours
    input_kwh = min(max_input_kwh, stored_needed_kwh / efficiency)
    stored_kwh = input_kwh * efficiency
    midnight_soc = min(start_soc + stored_kwh / capacity * 100.0, 100.0)

    return round(midnight_soc, 3), {
        "active": True,
        "basis": basis,
        "cheap_start": cheap_start.isoformat(),
        "handoff_end": midnight.isoformat(),
        "charge_hours_before_midnight": round(hours, 4),
        "starting_soc_percent": round(start_soc, 3),
        "projected_precheap_soc_percent": (
            round(projected_precheap, 3) if projected_precheap is not None else None
        ),
        "charge_input_kwh_before_midnight": round(input_kwh, 3),
        "stored_charge_kwh_before_midnight": round(stored_kwh, 3),
        "midnight_soc_percent": round(midnight_soc, 3),
        "charge_efficiency": round(efficiency, 4),
        "max_charge_kw": round(charge_kw, 3),
        "hardware_writes": "blocked",
    }
