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
    persisted_confirmed_windows: list[Mapping[str, Any]] | None = None,
    verified_receipts: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Estimate read-only credits from verified, independent one-hour rewards.

    The physical import ledger's persisted windows are historical confirmation
    evidence ONLY: they cannot authorise current or future grid import, charging,
    or FoxESS control. Each completed hour retains its verification, measured
    energy, and indicative rate after Octopus removes it from its joined feed.
    """
    unavailable: dict[str, Any] = {
        "estimated_credit_pence": None,
        "credited_import_kwh": None,
        "supplier_settled": False,
        "rate_basis": "rate captured with verified reward hour (indicative)",
        "verified_hour_receipts": [],
    }
    rate = _positive_number(import_rate_pence)
    gross = _positive_number(gross_import_cost_pence)
    if (
        rate is None or gross is None or not isinstance(now, datetime)
        or now.tzinfo is None
    ):
        return unavailable

    day = now.astimezone(_LONDON).date()
    confirmed: set[tuple[datetime, datetime]] = set()
    entries = bookings.get("bookings")
    for item in entries if isinstance(entries, list) else []:
        if not isinstance(item, Mapping):
            continue
        start, end = _datetime(item.get("start")), _datetime(item.get("end"))
        if (
            start is not None and end is not None
            and 0 < (end - start).total_seconds() <= 3600
            and (item.get("event_id") or item.get("event_code"))
        ):
            confirmed.add((start, end))

    # Only use windows saved by HappyHourImportLedgerRecorder while Octopus
    # booking authority was independently verified. Exact ONE-hour matches
    # are financial evidence after completion, never future booking authority.
    for item in persisted_confirmed_windows or []:
        if not isinstance(item, Mapping):
            continue
        start, end = _datetime(item.get("start")), _datetime(item.get("end"))
        if (
            start is not None and end is not None
            and 0 < (end - start).total_seconds() <= 3600
            and end <= now
        ):
            confirmed.add((start, end))

    receipts: dict[tuple[datetime, datetime], dict[str, Any]] = {}
    for item in verified_receipts or []:
        if not isinstance(item, Mapping):
            continue
        start, end = _datetime(item.get("start")), _datetime(item.get("end"))
        energy = _positive_number(item.get("import_kwh"))
        credit = _positive_number(item.get("credit_pence"))
        saved_rate = _positive_number(item.get("rate_pence"))
        if (
            start is None or end is None
            or not 0 < (end - start).total_seconds() <= 3600
            or start.astimezone(_LONDON).date() != day
            or energy is None or energy > 16.0
            or credit is None or saved_rate is None
        ):
            continue
        receipts[(start, end)] = {
            "start": start.isoformat(), "end": end.isoformat(),
            "import_kwh": energy, "credit_pence": credit,
            "rate_pence": saved_rate, "completed": bool(item.get("completed")),
        }

    hours = plan.get("reward_hours")
    for hour in hours if isinstance(hours, list) else []:
        if not isinstance(hour, Mapping) or hour.get("coverage_complete") is not True:
            continue
        start, end = _datetime(hour.get("start")), _datetime(hour.get("end"))
        if (
            start is None or end is None
            or not 0 < (end - start).total_seconds() <= 3600
            or start.astimezone(_LONDON).date() != day
            or start > now
        ):
            continue
        key = (start, end)
        previous = receipts.get(key)
        if key not in confirmed and previous is None:
            continue  # Publicly advertised events are never free-import proof.
        if previous is not None and previous["completed"]:
            continue  # A settled-in-ledger hour is never repriced by live rates.
        measured = _positive_number(hour.get("import_kwh"))
        cap = _positive_number(hour.get("cap_kwh"))
        if measured is None or cap is None:
            continue
        energy = min(measured, cap, 16.0)
        if previous is not None:
            energy = max(energy, previous["import_kwh"])
        locked_rate = previous["rate_pence"] if previous is not None else rate
        receipts[key] = {
            "start": start.isoformat(), "end": end.isoformat(),
            "import_kwh": round(energy, 3),
            "credit_pence": round(energy * locked_rate, 3),
            "rate_pence": locked_rate,
            "completed": end <= now,
        }

    if not receipts:
        return unavailable
    saved = [receipts[key] for key in sorted(receipts)]
    return {
        "estimated_credit_pence": round(
            min(sum(item["credit_pence"] for item in saved), gross), 3
        ),
        "credited_import_kwh": round(
            sum(item["import_kwh"] for item in saved), 3
        ),
        "supplier_settled": False,
        "rate_basis": "rate captured with verified reward hour (indicative)",
        "verified_reward_hours": len(saved),
        "verified_hour_receipts": saved,
    }
