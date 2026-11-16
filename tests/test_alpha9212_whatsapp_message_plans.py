"""Alpha9.212: WhatsApp pure event and completed reporting policy."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "kems"
    / "kems_core"
    / "whatsapp_message_plans.py"
)
SPEC = importlib.util.spec_from_file_location("alpha9212_whatsapp_policy", SOURCE)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _event(at: datetime, *, joined: bool = True, eid: str = "8375"):
    return {
        "event_id": eid,
        "start": at.isoformat(),
        "end": (at + timedelta(hours=1)).isoformat(),
        "joined": joined,
    }


def test_joined_only_with_durable_once_only_phases_and_rescheduled_identity():
    start = datetime(2026, 11, 17, 17, tzinfo=UTC)
    event = _event(start)
    planned = mod.event_notifications(
        category="Power Down",
        joined_events=[event, _event(start, joined=False, eid="unjoined")],
        now=start - timedelta(hours=1),
        sent_keys={},
    )
    assert len(planned) == 1
    assert "*⚡ Power Down — Confirmed booking*" in planned[0][1]
    assert (
        mod.event_notifications(
            category="Power Down",
            joined_events=[event],
            now=start - timedelta(minutes=45),
            sent_keys={planned[0][0]: "delivered"},
        )
        == []
    )
    started = mod.event_notifications(
        category="Power Down",
        joined_events=[event],
        now=start,
        sent_keys={planned[0][0]: "delivered"},
    )
    assert len(started) == 1 and "Started" in started[0][1]
    ended = mod.event_notifications(
        category="Power Down",
        joined_events=[event],
        now=start + timedelta(hours=1),
        sent_keys={},
    )
    assert "Supplier-settled rewards are not yet verified" in ended[0][1]
    assert (
        mod.event_notifications(
            category="Power Down",
            joined_events=[event],
            now=start + timedelta(hours=2),
            sent_keys={},
        )
        == []
    )
    updated = _event(start + timedelta(minutes=10))
    changed = mod.event_notifications(
        category="Power Down",
        joined_events=[updated],
        now=start - timedelta(minutes=20),
        sent_keys={planned[0][0]: "delivered"},
    )
    assert len(changed) == 1
    assert changed[0][0] != planned[0][0]


def test_happy_hour_does_not_announce_unjoined_suggestion():
    start = datetime(2026, 11, 21, 8, tzinfo=UTC)
    assert (
        mod.event_notifications(
            category="Happy Hour",
            joined_events=[_event(start, joined=False)],
            now=start - timedelta(hours=2),
            sent_keys={},
        )
        == []
    )


def test_london_dst_daily_and_weekly_previous_completed_periods():
    # Spring shift: local Monday morning, preceding Sunday is 23h.
    now = datetime(2026, 3, 30, 7, tzinfo=UTC)
    assert mod.morning_report_due(now, weekly=True)
    start, end = mod.recap_window(now, weekly=True)
    assert (start.isoformat(), end.isoformat()) == ("2026-03-23", "2026-03-29")
    assert mod.recap_window(now, weekly=False)[0].isoformat() == "2026-03-29"
    # Autumn shift: 25 Oct is 25h. 08:00 London is 08:00 UTC in November.
    autumn = datetime(2026, 10, 26, 8, tzinfo=UTC)
    assert mod.morning_report_due(autumn, weekly=True)
    assert mod.recap_window(autumn, weekly=False)[0].isoformat() == "2026-10-25"
    assert not mod.morning_report_due(autumn + timedelta(hours=2), weekly=True)


def test_stale_yesterday_label_and_incomplete_week_cannot_publish_old_money():
    now = datetime(2026, 11, 16, 8, tzinfo=UTC)
    periods = {
        "yesterday": {
            "start_date": "2026-11-14",
            "end_date": "2026-11-14",
            "days_included": 1,
            "complete_days": 1,
            "incomplete_days": 0,
            "data_complete": True,
            "export_income_pence": 99999,
        },
        "week": {
            "start_date": "2026-11-09",
            "end_date": "2026-11-15",
            "days_included": 7,
            "complete_days": 2,
            "incomplete_days": 4,
            "data_complete": False,
            "export_income_pence": 99999,
        },
    }
    _, daily = mod.completed_period_message(periods, now, weekly=False)
    _, weekly = mod.completed_period_message(periods, now, weekly=True)
    assert "missing or incomplete" in daily
    assert "missing or incomplete" in weekly
    assert "£999.99" not in daily + weekly


def test_completed_period_money_separates_export_hh_and_supplier_award():
    now = datetime(2026, 11, 16, 8, tzinfo=UTC)
    period = {
        "start_date": "2026-11-15",
        "end_date": "2026-11-15",
        "days_included": 1,
        "complete_days": 1,
        "incomplete_days": 0,
        "data_complete": True,
        "grid_export_kwh": 12.7,
        "grid_import_kwh": 3.2,
        "solar_generation_kwh": 2.4,
        "import_cost_pence": 100.0,
        "export_income_pence": 355.86,
        "gas_cost_pence": 72.0,
        "actual_net_cost_pence": -183.86,
        "happy_hour_estimated_credit_pence": 116.604,
    }
    _, message = mod.completed_period_message(
        {"calendar_matched": period}, now, weekly=False
    )
    assert "Agile export income: £3.56" in message
    assert "Happy Hour credit (estimated, not settled): £1.17" in message
    assert "Power Down verified reward: unavailable" in message
    assert "Net energy cost (reported actual): £-1.84" in message


def test_no_partial_or_invalid_price_is_fabricated():
    now = datetime(2026, 11, 16, 8, tzinfo=UTC)
    period = {
        "start_date": "2026-11-15",
        "end_date": "2026-11-15",
        "days_included": 1,
        "complete_days": 1,
        "incomplete_days": 0,
        "data_complete": True,
        "grid_export_kwh": float("nan"),
    }
    _, message = mod.completed_period_message({"a": period}, now, weekly=False)
    assert "Grid export: unavailable" in message
    assert "Agile export income: unavailable" in message


def test_first_send_unknown_notify_entity_is_allowed() -> None:
    unknown = mod.notify_entity_readiness(
        "notify.whatsapp_message", SimpleNamespace(state="unknown")
    )
    assert unknown == {
        "send_eligible": True,
        "status": "ready_for_first_send",
        "ha_state": "unknown",
    }
    other = mod.notify_entity_readiness(
        "notify.kems_private_alerts_message",
        SimpleNamespace(state="unknown"),
    )
    assert other["send_eligible"] is True


def test_real_unavailable_or_absent_targets_stay_blocked() -> None:
    assert (
        mod.notify_entity_readiness(
            "notify.whatsapp_message", SimpleNamespace(state="unavailable")
        )["send_eligible"]
        is False
    )
    assert (
        mod.notify_entity_readiness("notify.whatsapp_message", None)["status"]
        == "notify_entity_not_found"
    )
    assert (
        mod.notify_entity_readiness(
            "sensor.not_a_notifier", SimpleNamespace(state="ready")
        )["send_eligible"]
        is False
    )


def test_sent_notify_entity_remains_sendable() -> None:
    result = mod.notify_entity_readiness(
        "notify.whatsapp_message",
        SimpleNamespace(state="2026-11-16T20:37:00+00:00"),
    )
    assert result["send_eligible"] is True
    assert result["status"] == "ready"
