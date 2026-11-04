"""Read-only, provenance-rich event audit for reward-inclusive ROI."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .roi_rewards import date_of, number

_LONDON = ZoneInfo("Europe/London")


def _timestamp(value):
    try:
        result = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _window(start, end):
    a, b = _timestamp(start), _timestamp(end)
    if a is None or b is None:
        return None
    return (a.timestamp(), b.timestamp())


def _get(item, key):
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)


def _entry(kind, key, day, value, basis, settled, included, **extra):
    return {
        "type": kind,
        "reward_key": str(key),
        "date": day,
        "estimated_reward_pence": round(value, 3) if value is not None else None,
        "included_in_roi": bool(included),
        "evidence_source": basis,
        "supplier_settled": settled is True,
        "supplier_status": "settled" if settled is True else "unsettled",
        **extra,
    }


def build_reward_audit(
    happy_hours,
    power_downs,
    bookings,
    events,
    *,
    now,
    commissioning_date,
    max_entries=64,
):
    """Describe included and pending rewards without altering accounting."""
    today = now.astimezone(_LONDON).date().isoformat()
    start_day = commissioning_date.isoformat() if commissioning_date else None
    def eligible(day):
        return bool(
            start_day and isinstance(day, str) and start_day <= day <= today
        )
    verified_bookings = {}
    for booking in bookings:
        if (
            not isinstance(booking, dict)
            or booking.get("booking_source") != "octopus_joined_events"
        ):
            continue
        identity = _window(booking.get("start"), booking.get("end"))
        if identity is not None:
            verified_bookings[identity] = booking

    historical = {
        str(_get(event, "session_id")): event
        for event in events
        if _get(event, "session_id")
    }
    rows = []
    saved_windows = set()
    counted_happy = counted_power = unsettled = 0.0

    for key, receipt in happy_hours.items():
        if not isinstance(receipt, dict):
            continue
        parts = str(key).split("|", 1)
        if len(parts) != 2:
            continue
        identity = _window(*parts)
        if identity is None:
            continue
        saved_windows.add(identity)
        booking = verified_bookings.get(identity, {})
        amount = number(receipt.get("pence"))
        day = receipt.get("day")
        included = eligible(day) and amount is not None
        if included:
            counted_happy += amount
            if receipt.get("supplier_settled") is not True:
                unsettled += amount
        rows.append(
            _entry(
                "happy_hour",
                key,
                day,
                amount,
                receipt.get("basis"),
                receipt.get("supplier_settled"),
                included,
                event_id=booking.get("event_id"),
                start=parts[0],
                end=parts[1],
                booking_source=booking.get("booking_source"),
                status="included_estimate" if included else "excluded_from_roi",
            )
        )

    for key, receipt in power_downs.items():
        if not isinstance(receipt, dict):
            continue
        event = historical.get(str(key))
        amount = number(receipt.get("pence"))
        day = receipt.get("day")
        included = eligible(day) and amount is not None
        if included:
            counted_power += amount
            if receipt.get("supplier_settled") is not True:
                unsettled += amount
        rows.append(
            _entry(
                "power_down",
                key,
                day,
                amount,
                receipt.get("basis"),
                receipt.get("supplier_settled"),
                included,
                event_id=str(key),
                start=(
                    _get(event, "session_start").isoformat()
                    if isinstance(_get(event, "session_start"), datetime)
                    else None
                ),
                end=(
                    _get(event, "session_end").isoformat()
                    if isinstance(_get(event, "session_end"), datetime)
                    else None
                ),
                physical_export_verified=_get(event, "physical_export_verified"),
                physical_grid_export_kwh=_get(event, "physical_grid_export_kwh"),
                rewardable_reduction_kwh=_get(event, "rewardable_reduction_kwh"),
                status="included_modelled_bonus" if included else "excluded_from_roi",
            )
        )

    for identity, booking in verified_bookings.items():
        if identity in saved_windows:
            continue
        rows.append(
            _entry(
                "happy_hour",
                booking.get("event_id") or str(identity),
                date_of(booking.get("start")),
                None,
                "verified_booking_only",
                False,
                False,
                event_id=booking.get("event_id"),
                start=booking.get("start"),
                end=booking.get("end"),
                booking_source="octopus_joined_events",
                status="pending_individual_meter_and_tariff_receipt",
            )
        )

    for key, event in historical.items():
        if key in power_downs or _get(event, "available") is not True:
            continue
        end = _get(event, "session_end")
        rows.append(
            _entry(
                "power_down",
                key,
                date_of(end),
                None,
                "completed_event_without_independently_valued_bonus",
                False,
                False,
                event_id=key,
                start=(
                    _get(event, "session_start").isoformat()
                    if isinstance(_get(event, "session_start"), datetime)
                    else None
                ),
                end=end.isoformat() if isinstance(end, datetime) else None,
                physical_export_verified=_get(event, "physical_export_verified"),
                physical_grid_export_kwh=_get(event, "physical_grid_export_kwh"),
                rewardable_reduction_kwh=_get(event, "rewardable_reduction_kwh"),
                status="pending_bonus_or_baseline_evidence",
            )
        )

    rows.sort(
        key=lambda r: (r.get("date") or "", r.get("end") or "", r["reward_key"]),
        reverse=True,
    )
    return {
        "schema_version": 1,
        "reporting_only": True,
        "supplier_settlement_available": False,
        "included_happy_hour_pence": round(counted_happy, 6),
        "included_power_down_pence": round(counted_power, 6),
        "included_total_pence": round(counted_happy + counted_power, 6),
        "unsettled_total_pence": round(unsettled, 6),
        "included_count": sum(row["included_in_roi"] for row in rows),
        "pending_count": sum(row["estimated_reward_pence"] is None for row in rows),
        "entries": rows[:max_entries],
        "entries_omitted": max(len(rows) - max_entries, 0),
        "note": "Amounts are KEMS estimates; Octopus settlement is unconfirmed.",
    }
