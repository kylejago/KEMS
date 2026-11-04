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
        return bool(start_day and isinstance(day, str) and start_day <= day <= today)

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
    counted_happy = counted_power = unsettled = provisional = metered = 0.0

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
        is_provisional = str(receipt.get("basis") or "").startswith("provisional_")
        is_historical = (
            receipt.get("basis") == "provisional_historical_five_minute_meter_credit"
        )
        if included:
            counted_happy += amount
            if is_provisional:
                provisional += amount
            else:
                metered += amount
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
                covered_minutes=receipt.get("covered_minutes"),
                coverage_percent=receipt.get("coverage_percent"),
                observed_import_kwh=receipt.get("observed_import_kwh"),
                confidence=receipt.get("confidence"),
                rate_basis=receipt.get("rate_basis"),
                status=(
                    (
                        "included_provisional_historical_observation_estimate"
                        if is_historical
                        else "included_provisional_partial_estimate"
                    )
                    if included and is_provisional
                    else (
                        "included_meter_supported_estimate"
                        if included
                        else "excluded_from_roi"
                    )
                ),
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
            metered += amount
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
                modelled_agile_export_income_pence=_get(
                    event, "fixed_export_income_pence"
                ),
                agile_export_income_already_counted=True,
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
                modelled_agile_export_income_pence=_get(
                    event, "fixed_export_income_pence"
                ),
                agile_export_income_already_counted=True,
                status="pending_bonus_or_baseline_evidence",
            )
        )

    rows.sort(
        key=lambda r: (r.get("date") or "", r.get("end") or "", r["reward_key"]),
        reverse=True,
    )
    commissioned_rows = [row for row in rows if eligible(row.get("date"))]
    happy_rows = [row for row in commissioned_rows if row["type"] == "happy_hour"]
    power_rows = [row for row in commissioned_rows if row["type"] == "power_down"]
    historical_coverage = {
        "commissioning_date": start_day,
        "through_date": today,
        "scope": "known_joined_happy_hours_and_persisted_power_down_events",
        "known_happy_hour_hours": len(happy_rows),
        "happy_hour_hours_in_roi": sum(r["included_in_roi"] for r in happy_rows),
        "happy_hour_hours_pending_evidence": sum(
            r["estimated_reward_pence"] is None for r in happy_rows
        ),
        "known_power_down_events": len(power_rows),
        "power_down_events_in_roi": sum(r["included_in_roi"] for r in power_rows),
        "power_down_events_pending_evidence": sum(
            r["estimated_reward_pence"] is None for r in power_rows
        ),
        "all_historical_sessions_discovered": False,
        "note": (
            "Counts include only historically witnessed and independently booked "
            "events. The supplier joined-event feed may omit older sessions; "
            "no historical coverage or payment is assumed without evidence."
        ),
    }
    return {
        "schema_version": 2,
        "historical_coverage": historical_coverage,
        "reporting_only": True,
        "supplier_settlement_available": False,
        "included_happy_hour_pence": round(counted_happy, 6),
        "included_power_down_pence": round(counted_power, 6),
        "included_total_pence": round(counted_happy + counted_power, 6),
        "unsettled_total_pence": round(unsettled, 6),
        "provisional_partial_pence": round(provisional, 6),
        "meter_supported_estimate_pence": round(metered, 6),
        "included_count": sum(row["included_in_roi"] for row in rows),
        "pending_count": sum(row["estimated_reward_pence"] is None for row in rows),
        "entries": rows[:max_entries],
        "entries_omitted": max(len(rows) - max_entries, 0),
        "note": (
            "Historical five-minute Happy Hour estimates and live partial-hour "
            "credits cover only witnessed meter intervals. Missing periods "
            "are never interpolated. Power Down Agile earnings "
            "are displayed for context but never added to ROI twice. "
            "Octopus settlement is unconfirmed."
        ),
    }
