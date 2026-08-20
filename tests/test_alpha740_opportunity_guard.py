from datetime import UTC, datetime, timedelta

from custom_components.kems.agile_alpha740_opportunity_guard import _economic_guard


def _slot(start: datetime, rate: float) -> dict:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "rate_pence": rate,
    }


def test_current_better_slot_gets_proactive_export_floor() -> None:
    now = datetime(2026, 8, 20, 14, 10, tzinfo=UTC)
    current = _slot(now.replace(minute=0), 12.27)
    future_a = _slot(now.replace(minute=30), 11.95)
    future_b = _slot(now.replace(hour=15, minute=0), 10.20)
    state = {"today_slots": [current, future_a, future_b]}
    plan = {
        "exportable_battery_energy_kwh": 4.0,
        "planned_battery_export_kwh": 4.0,
    }

    guard = _economic_guard(state, plan, now=now, effective_kw=7.0)

    assert guard["active"] is True
    assert guard["current_rate_pence"] == 12.27
    assert guard["price_advantage_pence"] > 0
    assert guard["minimum_current_export_kwh"] > 0


def test_worse_current_slot_does_not_preempt_better_future_slots() -> None:
    now = datetime(2026, 8, 20, 14, 10, tzinfo=UTC)
    current = _slot(now.replace(minute=0), 8.0)
    future_a = _slot(now.replace(minute=30), 12.0)
    future_b = _slot(now.replace(hour=15, minute=0), 11.0)
    state = {"today_slots": [current, future_a, future_b]}
    plan = {
        "exportable_battery_energy_kwh": 2.0,
        "planned_battery_export_kwh": 2.0,
    }

    guard = _economic_guard(state, plan, now=now, effective_kw=7.0)

    assert guard["active"] is False
    assert guard["minimum_current_export_kwh"] == 0
