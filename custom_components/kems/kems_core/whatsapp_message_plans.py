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
    return f"£{number / 100:.2f}" if isfinite(number) else "unavailable"


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if isfinite(number) else None


def completed_period_message(
    periods: Mapping[str, Any],
    now: datetime,
    weekly: bool,
    *,
    standing_charge_pence_per_day: float | None = None,
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
