"""Regression checks for the pure WhatsApp templates (no HA needed)."""

from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from zoneinfo import ZoneInfo

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components/kems/kems_core/whatsapp_message_plans.py"
)
spec = spec_from_file_location("kems_whatsapp_template_tests", MODULE_PATH)
assert spec is not None and spec.loader is not None
messages = module_from_spec(spec)
spec.loader.exec_module(messages)


def test_confirmed_events_only_and_rich_format():
    now = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    joined = {
        "joined": True,
        "event_id": "confirmed-1",
        "start": now + timedelta(hours=2),
        "end": now + timedelta(hours=3),
    }
    result = messages.event_notifications(
        category="Happy Hour",
        joined_events=[joined, {**joined, "joined": False}],
        now=now,
        sent_keys={},
    )
    assert len(result) == 1
    assert "🟢 Happy Hour" in result[0][1]
    assert "✅ Joined" in result[0][1]
    assert messages.event_notifications(
        category="Happy Hour", joined_events=[joined], now=now,
        sent_keys={result[0][0]: now.isoformat()},
    ) == []


def test_daily_recap_financial_labels():
    now = datetime(2026, 11, 16, 8, 1, tzinfo=ZoneInfo("Europe/London"))
    day = "2026-11-15"
    period = {
        "start_date": day, "end_date": day,
        "data_complete": True, "complete_days": 1,
        "days_included": 1, "incomplete_days": 0,
        "grid_import_kwh": 12.5, "grid_export_kwh": 18.4,
        "solar_generation_kwh": 8.2, "import_cost_pence": 145,
        "export_income_pence": 276, "gas_cost_pence": 85,
        "actual_net_cost_pence": -46,
        "happy_hour_estimated_credit_pence": 120,
    }
    key, text = messages.completed_period_message(
        {"yesterday": period}, now, weekly=False
    )
    assert key == "recap:daily:2026-11-15:2026-11-15"
    assert "*💷 Actual energy finances*" in text
    assert "£-0.46" in text
    assert "£1.20" in text and "estimated, not settled" in text
    assert "Power Down verified reward: unavailable" in text


def test_incomplete_recap_never_fabricates_costs():
    now = datetime(2026, 11, 16, 8, tzinfo=UTC)
    _, text = messages.completed_period_message({}, now, weekly=True)
    assert "Report not yet available" in text
    assert "No costs, savings or rewards have been inferred" in text
