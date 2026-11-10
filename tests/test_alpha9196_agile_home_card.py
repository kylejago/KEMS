"""The managed Home Agile card distinguishes house-only use and advisory SOC."""

from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"


def _card_template():
    """Render the real packaged Home card, not a copy of its Jinja logic."""
    assert SOURCE.read_bytes() == PACKAGED.read_bytes()
    data = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    card = next(
        card
        for card in data["views"][0]["cards"]
        if card.get("title") == "Today's Agile plan — now and next"
    )
    return Environment().from_string(card["content"])


def _numeric(value):
    try:
        return isfinite(float(value))
    except (ValueError, TypeError):
        return False


def _scenario():
    start = datetime.fromisoformat("2026-11-10T00:00:00+00:00")
    today = []
    for index in range(48):
        begin = start + timedelta(minutes=30 * index)
        today.append(
            {
                "label": begin.strftime("%H:%M"),
                "valid_from": begin.isoformat(),
                "valid_to": (begin + timedelta(minutes=30)).isoformat(),
                "rate_pence": 16.7,
            }
        )
    active, future, cheap = today[45], today[46], today[47]
    for item, basis, soc in (
        (active, "canonical current routing snapshot", 14.3),
        (future, "KEMS forecast + final rolling allocation", 13.4),
        (cheap, "KEMS forecast + final rolling allocation", 20.2),
    ):
        item.update(
            {
                "flow_basis": basis,
                "flow_estimated_soc_percent": soc,
                "planning_target_limits_export_only": True,
                "hard_safety_floor_latched": False,
                "flow_battery_to_home_kwh": 0.0,
                "flow_grid_to_battery_kwh": 0.0,
            }
        )
    active["flow_battery_to_home_kwh"] = 0.226
    future["flow_battery_to_home_kwh"] = 0.497
    future["actions"] = ["hold — total-discharge / price replan"]
    cheap["actions"] = ["cheap charge"]
    cheap["flow_grid_to_battery_kwh"] = 3.325
    tomorrow = [dict(item) for item in today]
    outlook = {
        active["valid_from"]: {"action": "Hold — no battery export planned"},
        future["valid_from"]: {"action": "Hold — no battery export planned"},
        cheap["valid_from"]: {"action": "Hold — no battery export planned"},
    }
    return {
        "today_slots": today,
        "tomorrow_slots": tomorrow,
        "physical_live_slot_outlook": outlook,
        "published_plan_slot_outlook": {},
        "physical_live_slot_outlook_current_soc_percent": 13.915,
        "observed_foxess_soc_percent": 14.0,
    }


def _render(data, *, power_down=False):
    return _card_template().render(
        state_attr=lambda _entity, attribute: data.get(attribute),
        now=lambda: datetime(2026, 11, 10, 22, 50),
        is_number=_numeric,
        is_state=lambda entity, expected: (
            power_down
            and entity == "binary_sensor.kems_power_down_session_active"
            and expected == "on"
        ),
    )


def test_inactive_solar_forecast_fallback_shows_house_use_and_soc() -> None:
    result = _render(_scenario())
    assert "Battery powers house · no deliberate export" in result
    assert "Cheap charging forecast · house on grid" in result
    assert "**FoxESS SOC:** 14.0%" in result
    assert "15% deliberate-export stop" in result
    assert "conservative discharge-only physical ledger" in result
    # No independent physical future SOC proof: never show simulated numbers.
    assert "~14.3%" not in result
    assert "~13.4%" not in result
    assert "~20.2%" not in result
    assert "| 23:00 |" in result
    assert " | — |" in result


def test_verified_physical_soc_takes_precedence_over_advisory() -> None:
    scenario = _scenario()
    key = scenario["today_slots"][45]["valid_from"]
    scenario["physical_live_slot_outlook"][key]["estimated_soc_percent"] = 14.1
    result = _render(scenario)
    assert "14.1%" in result
    assert "~14.3%" not in result
    assert "~13.4%" not in result
    assert "~20.2%" not in result


def test_priority_event_keeps_physical_action_and_suppresses_advisory_soc() -> None:
    scenario = _scenario()
    key = scenario["today_slots"][45]["valid_from"]
    scenario["physical_live_slot_outlook"][key]["action"] = "Power Down event priority"
    result = _render(scenario, power_down=True)
    assert "Power Down event priority" in result
    assert "Battery powers house · no deliberate export" not in result
    assert "Cheap charging forecast · house on grid" not in result
    assert "~13.4%" not in result


def test_missing_future_flow_does_not_fabricate_home_action_or_soc() -> None:
    scenario = _scenario()
    key = scenario["today_slots"][46]["valid_from"]
    future = scenario["today_slots"][46]
    future["flow_basis"] = "settled/replayed KEMS slot"
    future["flow_estimated_soc_percent"] = None
    future["flow_battery_to_home_kwh"] = None
    scenario["physical_live_slot_outlook"][key][
        "action"
    ] = "Hold — no battery export planned"
    result = _render(scenario)
    assert "Hold — no battery export planned" in result
    assert "~13.4%" not in result
