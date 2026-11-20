"""Pure, source-constrained WhatsApp notification planning (no HA control)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return result.astimezone(UTC) if result.tzinfo is not None else None


def event_notifications(
    *,
    category: str,
    joined_events: list[Mapping[str, Any]],
    now: datetime,
    sent_keys: Mapping[str, Any],
) -> list[tuple[str, str]]:
    """Only independently joined, future/live event notifications.

    Names, source and event boundaries are included in dedupe keys so a
    corrected external booking time is announced once without losing the
    previous booking's history. Unjoined proposals are never accepted.
    """
    if category not in {"Power Down", "Happy Hour"} or now.tzinfo is None:
        return []
    messages: list[tuple[str, str]] = []
    seen: set[str] = set()
    for event in joined_events:
        if event.get("joined") is not True:
            continue
        start = _aware(event.get("start"))
        end = _aware(event.get("end"))
        event_id = str(event.get("event_id") or "").strip()
        if start is None or end is None or end <= start or not event_id:
            continue
        identity = f"{category}:{event_id}:{start.isoformat()}:{end.isoformat()}"
        if identity in seen:
            continue
        seen.add(identity)
        date_label = start.astimezone(LONDON).strftime("%a %d %b, %H:%M")
        end_label = end.astimezone(LONDON).strftime("%H:%M %Z")
        display = f"{date_label}–{end_label}"
        label = "⚡ Power Down" if category == "Power Down" else "🟢 Happy Hour"
        if now < start <= now + timedelta(hours=24):
            phase = "planned"
            message = (
                f"*{label} — Confirmed booking*\n"
                f"📅 {display}\n"
                "✅ Joined with Octopus\n"
                "KEMS will follow its configured event controls."
            )
        elif start <= now < start + timedelta(minutes=2):
            phase = "started"
            message = (
                f"*{label} — Started*\n"
                f"🕒 {display}\n"
                "✅ Confirmed joined session is active."
            )
        elif end <= now < end + timedelta(minutes=2):
            phase = "ended"
            message = (
                f"*{label} — Finished*\n"
                f"🕒 {display}\n"
                "💷 Supplier-settled rewards are not yet verified. "
                "Any estimated credit is separate from confirmed earnings."
            )
        else:
            continue
        key = f"{identity}:{phase}"
        if key not in sent_keys:
            messages.append((key, message))
    return messages


def _period_day(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _field(period: Any, key: str) -> Any:
    return (
        period.get(key) if isinstance(period, Mapping) else getattr(period, key, None)
    )


def matching_completed_period(
    periods: Mapping[str, Any],
    start: date,
    end: date,
) -> Any | None:
    """Match exact London calendar boundaries, including partial day ledgers."""
    if not isinstance(periods, Mapping):
        return None
    for period in periods.values():
        if (
            _period_day(_field(period, "start_date")) == start
            and _period_day(_field(period, "end_date")) == end
        ):
            return period
    return None


def recap_window(now: datetime, weekly: bool) -> tuple[date, date]:
    """Previous completed London calendar day or Monday–Sunday week."""
    local_day = now.astimezone(LONDON).date()
    if weekly:
        end = local_day - timedelta(days=local_day.weekday() + 1)
        return end - timedelta(days=6), end
    yesterday = local_day - timedelta(days=1)
    return yesterday, yesterday


def _quantity(value: Any, units: str) -> str:
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return "unavailable"
    if not isfinite(number):
        return "unavailable"
    return f"{number:.2f} {units}"


def _pounds(pence: Any) -> str:
    try:
        number = float(pence)
    except (ValueError, TypeError, OverflowError):
        return "unavailable"
    if not isfinite(number):
        return "unavailable"
    return f"−£{abs(number) / 100:.2f}" if number < 0 else f"£{number / 100:.2f}"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if isfinite(number) else None


def _bill_effective_total(
    bill_equivalent_periods: Mapping[str, Any] | None,
    start: date,
    end: date,
) -> float | None:
    """Return the canonical refund-adjusted energy bill for the exact period.

    A stale or incomplete dashboard snapshot must never override the recorded
    period ledger. The canonical bill includes electricity, gas, standing
    charges, export credits and eligible estimated Happy Hour refunds.
    """
    period = matching_completed_period(bill_equivalent_periods, start, end)
    if period is None:
        return None
    if _number(_field(period, "days_included")) != (end - start).days + 1:
        return None
    live = _field(period, "live_data")
    if not isinstance(live, Mapping) or _field(live, "ready") is not True:
        return None
    return _number(_field(live, "total_energy_effective_cost_pence"))


def completed_period_message(
    periods: Mapping[str, Any],
    now: datetime,
    weekly: bool,
    *,
    standing_charge_pence_per_day: float | None = None,
    bill_equivalent_periods: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Publish recorded totals with explicit incomplete-coverage provenance.

    The KEMS period ledger's actual_net_cost_pence excludes electricity
    standing charge. Dashboard gross cost includes it once per calendar day.
    Never claim a complete bill if one or more days are incomplete.
    """
    start, end = recap_window(now, weekly)
    kind = "weekly" if weekly else "daily"
    key = f"recap:{kind}:{start.isoformat()}:{end.isoformat()}"
    title = (
        f"📅 *KEMS — Weekly Energy Summary*\n{start:%d %b}–{end:%d %b %Y}"
        if weekly
        else f"📊 *KEMS — Daily Energy Summary*\n{start:%d %b %Y}"
    )
    period = matching_completed_period(periods, start, end)
    if period is None or not _number(_field(period, "days_included")):
        return (
            key,
            f"{title}\n\n⚠️ *No recorded period totals available*\n"
            "No costs, savings or rewards have been inferred.",
        )

    # New ledgers distinguish saved totals from simulator replay. Older
    # diagnostics have no explicit availability field, so retain legacy
    # presence-based compatibility for their already-recorded figures.
    if _field(period, "recorded_totals_available") is False:
        return (
            key,
            f"{title}\n\n⚠️ *No recorded period totals available*\n"
            "No costs, savings or rewards have been inferred.",
        )

    days = (end - start).days + 1
    included = int(_number(_field(period, "days_included")) or 0)
    complete = int(_number(_field(period, "complete_days")) or 0)
    replay_complete = _field(period, "simulation_coverage_complete")
    if replay_complete is None:
        replay_complete = _field(period, "data_complete")
    fully_covered = (
        replay_complete is True
        and included == days
        and complete == days
        and _field(period, "incomplete_days") == 0
    )
    coverage = (
        "✅ Recorded totals available; simulation replay coverage complete. "
        "Independent meter completeness not verified."
        if fully_covered
        else f"⚠️ *Partial coverage* — simulation replay "
        f"({complete}/{days} complete days; {included}/{days} days recorded). "
        "Saved totals are shown, but missing intervals may understate them. "
        "Independent meter completeness not verified."
    )

    standing_daily = _number(standing_charge_pence_per_day)
    base_net = _number(_field(period, "actual_net_cost_pence"))
    estimated_refund = _number(_field(period, "happy_hour_estimated_credit_pence"))
    standing = standing_daily * days if standing_daily is not None else None
    gross = (
        base_net + standing if base_net is not None and standing is not None else None
    )
    after_credit = (
        gross - estimated_refund
        if gross is not None and estimated_refund is not None
        else None
    )

    if not weekly:
        # Use the same canonical, refund-adjusted TOTAL ENERGY COST as the
        # dashboard. Only fall back to the period ledger's refund-adjusted
        # estimate when an exact-date canonical bill is unavailable.
        bill_total = _bill_effective_total(bill_equivalent_periods, start, end)
        daily_total = bill_total if bill_total is not None else after_credit
        # Coverage and unsettled credit details remain in KEMS diagnostics
        # and the separate detailed weekly summary.
        return key, "\n".join(
            [
                title,
                "",
                f"⬇️ Grid import: {_quantity(_field(period, 'grid_import_kwh'), 'kWh')}",
                f"⬆️ Grid export: {_quantity(_field(period, 'grid_export_kwh'), 'kWh')}",
                "☀️ Solar generated: "
                + _quantity(_field(period, "solar_generation_kwh"), "kWh"),
                f"💷 *Energy total: {_pounds(daily_total)}*",
            ]
        )

    lines = [
        title,
        coverage,
        "",
        "*⚡ Recorded energy*",
        f"⬇️ Grid import: {_quantity(_field(period, 'grid_import_kwh'), 'kWh')}",
        f"⬆️ Grid export: {_quantity(_field(period, 'grid_export_kwh'), 'kWh')}",
        "☀️ Solar generated: "
        + _quantity(_field(period, "solar_generation_kwh"), "kWh"),
        "",
        "*💷 Recorded finances*",
        f"Electricity import: {_pounds(_field(period, 'import_cost_pence'))}",
        f"Electricity standing charge: {_pounds(standing)}",
        f"Agile export income: {_pounds(_field(period, 'export_income_pence'))}",
        f"Gas cost: {_pounds(_field(period, 'gas_cost_pence'))}",
        f"*Gross energy total (dashboard basis): {_pounds(gross)}*",
        "",
        "*🎁 Event credits*",
        "Happy Hour refund (estimated, unsettled): " + _pounds(estimated_refund),
        "Power Down supplier-confirmed award: unavailable in period ledger",
        "*Net after estimated Happy Hour refund: " + _pounds(after_credit) + "*",
        "",
        "ℹ️ Estimated refunds are not supplier-confirmed. "
        "A partial report is not a verified full-period bill.",
    ]
    return key, "\n".join(lines)


def morning_report_due(now: datetime, weekly: bool) -> bool:
    local = now.astimezone(LONDON)
    return (
        local.hour == 8 and local.minute < 15 and (not weekly or local.weekday() == 0)
    )


def notify_entity_readiness(entity_id: Any, state: Any) -> dict[str, Any]:
    """HA NotifyEntity state is UNKNOWN until its first successful send.

    A registered notify entity in the unknown state is a valid first-send
    destination. Missing or explicitly unavailable entities fail closed.
    Never attempt sending to a guessed service or a non-notify entity.
    """
    if not isinstance(entity_id, str) or not entity_id.startswith("notify."):
        return {
            "send_eligible": False,
            "status": "invalid_notify_entity",
            "ha_state": None,
        }
    if state is None:
        return {
            "send_eligible": False,
            "status": "notify_entity_not_found",
            "ha_state": None,
        }
    value = getattr(state, "state", None)
    if value == "unavailable":
        return {
            "send_eligible": False,
            "status": "notify_entity_unavailable",
            "ha_state": value,
        }
    if value is None:
        return {
            "send_eligible": False,
            "status": "missing_notify_entity_state",
            "ha_state": None,
        }
    return {
        "send_eligible": True,
        "status": ("ready_for_first_send" if value == "unknown" else "ready"),
        "ha_state": value,
    }


def regular_offpeak_message(
    *,
    state: str,
    changed_at: datetime,
    now: datetime,
) -> tuple[str, str] | None:
    """Only observed normal tariff off-peak ON/OFF transitions.

    Independent of the optional Intelligent extra-slot sensor. Never infer
    an event from tariff price alone or reconstruct one after an HA restart.
    """
    if state not in {"on", "off"} or now.tzinfo is None or changed_at.tzinfo is None:
        return None
    age = (now - changed_at).total_seconds()
    if not -15 <= age <= 300:
        return None
    timestamp = changed_at.astimezone(LONDON)
    key = "regular-offpeak:" + state + ":" + changed_at.astimezone(UTC).isoformat()
    if state == "on":
        return (
            key,
            "⚡ *Octopus Off-Peak Active*\n"
            f"🕒 Start: {timestamp:%H:%M}\n"
            "The regular cheap import period is active. "
            "KEMS will power the home from the grid and charge the battery when safe.",
        )
    return (
        key,
        "⚡ *Octopus Off-Peak Ended*\n"
        f"🕒 End: {timestamp:%H:%M}\n"
        "KEMS has returned to its normal battery and Agile export protections.",
    )


def intelligent_slot_message(
    *,
    state: str,
    changed_at: datetime,
    now: datetime,
    end_time: Any = None,
) -> tuple[str, str] | None:
    """Announce observed Octopus Intelligent slot transitions, not rate guesses.

    Use the observed binary-sensor transition timestamp as the real start or
    end. The next_offpeak_start entity can refer to a later slot, so it
    must not be mistaken for the start of the currently active slot.
    """
    if state not in {"on", "off"} or now.tzinfo is None or changed_at.tzinfo is None:
        return None
    age = (now - changed_at).total_seconds()
    if not -15 <= age <= 300:
        return None
    timestamp = changed_at.astimezone(LONDON)
    key = "intelligent-slot:" + state + ":" + changed_at.astimezone(UTC).isoformat()
    if state == "off":
        return (
            key,
            "⚡ *Octopus Intelligent — Cheap Slot Ended*\n"
            f"🕒 End: {timestamp:%H:%M}\n"
            "The Intelligent Octopus cheap slot has ended. ✅\n"
            "KEMS continues to follow its configured battery and EV protections.",
        )
    end = _aware(end_time)
    valid_end = (
        end is not None
        and end >= changed_at
        and end <= changed_at + timedelta(hours=24)
    )
    end_label = end.astimezone(LONDON).strftime("%H:%M") if valid_end else "TBC"
    return (
        key,
        "⚡ *Octopus Intelligent — Cheap Slot Active*\n"
        f"🕒 Start: {timestamp:%H:%M}\n"
        f"🕓 End: {end_label}\n"
        "Good news — an Intelligent Octopus cheap slot is active! 🔋💡\n"
        "KEMS will continue to enforce its EV and home-battery protections.",
    )



def ohme_charging_message(
    *,
    state: str,
    observed_at: datetime,
    now: datetime,
) -> tuple[str, str] | None:
    """Announce *observed charger activity*, never a supplier-discount claim.

    KEMS observes the physical Ohme charge transition after a fresh power and
    charging-state check. It cannot infer the exact start or end time, so the
    timestamp is explicitly the time KEMS observed the transition.
    """
    if state not in {"on", "off"} or now.tzinfo is None or observed_at.tzinfo is None:
        return None
    age = (now - observed_at).total_seconds()
    if not -15 <= age <= 300:
        return None
    timestamp = observed_at.astimezone(LONDON)
    key = "ohme-charge:" + state + ":" + observed_at.astimezone(UTC).isoformat()
    if state == "on":
        return (
            key,
            "🔌 *Ohme — EV Charging Started*\n"
            f"🕒 Observed: {timestamp:%H:%M}\n"
            "KEMS has observed the charger drawing power. "
            "This does not confirm an Octopus discounted slot or whole-home cheap rate.\n"
            "KEMS continues to protect the home battery.",
        )
    return (
        key,
        "🔌 *Ohme — EV Charging Stopped*\n"
        f"🕒 Observed: {timestamp:%H:%M}\n"
        "KEMS has observed charging stop. This is not evidence that an "
        "Octopus discounted period has ended. Battery protection remains active.",
    )
