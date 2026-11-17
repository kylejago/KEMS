"""Alpha9.221: compact WhatsApp daily recap and unchanged detailed weekly format."""

from __future__ import annotations

from datetime import UTC, datetime

from kems_core.whatsapp_message_plans import completed_period_message


def test_daily_recap_matches_user_requested_five_fields_exactly() -> None:
    now = datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
    yesterday = {
        "start_date": "2026-11-16",
        "end_date": "2026-11-16",
        "days_included": 1,
        "complete_days": 0,
        "incomplete_days": 1,
        "data_complete": False,
        "recorded_totals_available": True,
        "grid_import_kwh": 48.0,
        "grid_export_kwh": 15.2,
        "solar_generation_kwh": 4.3,
        "actual_net_cost_pence": -17.04,
        "happy_hour_estimated_credit_pence": 500.0,
    }
    key, message = completed_period_message(
        {"yesterday": yesterday},
        now,
        weekly=False,
        standing_charge_pence_per_day=55.5236,
    )
    assert key == "recap:daily:2026-11-16:2026-11-16"
    assert message == (
        "📊 *KEMS — Daily Energy Summary*\n"
        "16 Nov 2026\n\n"
        "⬇️ Grid import: 48.00 kWh\n"
        "⬆️ Grid export: 15.20 kWh\n"
        "☀️ Solar generated: 4.30 kWh\n"
        "💷 *Energy total: £0.38*"
    )


def test_daily_recap_does_not_mask_missing_cost_or_kwh() -> None:
    now = datetime(2026, 11, 17, 8, tzinfo=UTC)
    period = {
        "start_date": "2026-11-16",
        "end_date": "2026-11-16",
        "days_included": 1,
        "recorded_totals_available": True,
        "grid_import_kwh": 2.0,
        "grid_export_kwh": float("nan"),
        "solar_generation_kwh": None,
        "actual_net_cost_pence": None,
    }
    _, message = completed_period_message(
        {"yesterday": period},
        now,
        weekly=False,
        standing_charge_pence_per_day=55.5236,
    )
    assert "Grid import: 2.00 kWh" in message
    assert "Grid export: unavailable" in message
    assert "Solar generated: unavailable" in message
    assert "Energy total: unavailable" in message
    assert "£0.00" not in message
    assert "Partial coverage" not in message


def test_weekly_report_keeps_detailed_provenance_and_credits() -> None:
    now = datetime(2026, 11, 16, 8, tzinfo=UTC)
    week = {
        "start_date": "2026-11-09",
        "end_date": "2026-11-15",
        "days_included": 7,
        "complete_days": 2,
        "incomplete_days": 5,
        "data_complete": False,
        "recorded_totals_available": True,
        "grid_import_kwh": 120.5,
        "grid_export_kwh": 75.0,
        "solar_generation_kwh": 36.2,
        "import_cost_pence": 2500.0,
        "export_income_pence": 3000.0,
        "gas_cost_pence": 200.0,
        "actual_net_cost_pence": -300.0,
        "happy_hour_estimated_credit_pence": 100.0,
    }
    _, message = completed_period_message(
        {"last_week": week},
        now,
        weekly=True,
        standing_charge_pence_per_day=55.5236,
    )
    assert "Partial coverage" in message
    assert "Recorded finances" in message
    assert "Event credits" in message
    assert "Gross energy total (dashboard basis)" in message
    assert "Happy Hour refund (estimated, unsettled)" in message
