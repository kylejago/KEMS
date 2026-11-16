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
        if now < start <= now + timedelta(hours=24):
            phase, message = (
                "planned",
                f"KEMS {category}: confirmed joined session planned for {display}.",
            )
        elif start <= now < start + timedelta(minutes=2):
            phase, message = (
                "started",
                f"KEMS {category}: confirmed session started ({display}).",
            )
        elif end <= now < end + timedelta(minutes=2):
            phase, message = (
                "ended",
                f"KEMS {category}: session ended ({display}). "
                "Final supplier-settled reward is not yet verified.",
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
    """Never assume 'yesterday', 'week' or 'last_week' date labels are fresh."""
    if not isinstance(periods, Mapping):
        return None
    wanted_days = (end - start).days + 1
    for period in periods.values():
        if (
            _period_day(_field(period, "start_date")) != start
            or _period_day(_field(period, "end_date")) != end
        ):
            continue
        if (
            _field(period, "data_complete") is True
            and _field(period, "complete_days") == wanted_days
            and _field(period, "incomplete_days") == 0
            and _field(period, "days_included") == wanted_days
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


def completed_period_message(
    periods: Mapping[str, Any], now: datetime, weekly: bool
) -> tuple[str, str]:
    """A calendar-correct recap; incomplete history has no invented figures."""
    start, end = recap_window(now, weekly)
    kind = "weekly" if weekly else "daily"
    key = f"recap:{kind}:{start.isoformat()}:{end.isoformat()}"
    title = (
        f"KEMS weekly recap: {start:%d %b}–{end:%d %b %Y}"
        if weekly
        else f"KEMS yesterday: {start:%d %b %Y}"
    )
    period = matching_completed_period(periods, start, end)
    if period is None:
        return (
            key,
            f"{title}\nCompleted-period figures unavailable or incomplete. "
            "No costs, savings or rewards have been inferred.",
        )
    lines = [
        title,
        f"Grid import: {_quantity(_field(period, 'grid_import_kwh'), 'kWh')}",
        f"Grid export: {_quantity(_field(period, 'grid_export_kwh'), 'kWh')}",
        f"Solar generated: {_quantity(_field(period, 'solar_generation_kwh'), 'kWh')}",
        f"Import cost: {_pounds(_field(period, 'import_cost_pence'))}",
        f"Agile export income: {_pounds(_field(period, 'export_income_pence'))}",
        f"Gas cost: {_pounds(_field(period, 'gas_cost_pence'))}",
        "Net energy cost before Happy Hour estimates: "
        + _pounds(_field(period, "actual_net_cost_pence")),
        "Happy Hour credit (estimated, not supplier-settled): "
        + _pounds(_field(period, "happy_hour_estimated_credit_pence")),
        "Power Down supplier awards for this period: unavailable "
        "(not included in the period energy figures).",
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
        "status": (
            "ready_for_first_send" if value == "unknown" else "ready"
        ),
        "ha_state": value,
    }
