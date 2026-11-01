"""Alpha9.104: Home is a live operational dashboard, not a simulation pane."""

from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "dashboards/kems_master_dashboard.yaml"
PACKAGED = ROOT / "custom_components/kems/kems_master_dashboard.yaml"


def _home() -> dict:
    dashboard = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    return dashboard["views"][0]


def test_live_home_keeps_stable_navigation_and_packaged_parity() -> None:
    assert SOURCE.read_bytes() == PACKAGED.read_bytes()
    home = _home()
    assert home["title"] == "Home"
    assert home["path"] == "home"
    assert home["icon"] == "mdi:home-lightning-bolt"
    assert all(
        card["type"] in {"markdown", "grid", "entities"} for card in home["cards"]
    )


def test_live_home_excludes_digital_twin_and_uses_actual_energy() -> None:
    home = _home()
    text = str(home)
    for expected in (
        "sensor.kems_house_load",
        "sensor.kems_grid_import",
        "sensor.kems_grid_export",
        "sensor.kems_battery_power",
        "sensor.kems_battery_state_of_charge",
        "sensor.kems_observed_grid_import_today",
        "sensor.kems_observed_grid_export_today",
        "sensor.kems_observed_solar_generation_today",
        "sensor.kems_energy_cost_comparison",
        "total_energy_cost_pence",
        "electricity_export_income_pence",
    ):
        assert expected in text
    assert "sensor.kems_simulated_" not in text
    assert "Today — Live Data vs KEMS" not in text


def test_live_home_shows_agile_power_down_and_happy_hour_plans() -> None:
    text = str(_home())
    assert "sensor.kems_agile_slots" in text
    assert "physical_live_slot_outlook" in text
    assert "rolling_action" not in text
    assert "today[idx:idx + 6]" in text
    assert "sensor.kems_next_power_down_session_start" in text
    assert "saving_session_export_target_kw" in text
    assert "No upcoming Power Down session" in text
    assert "switch.kems_weekend_happy_hour_auto_join" in text
    assert "booked_start" in text
    assert "recommended_start" in text
    assert "Recommended, not booked" in text
    assert "current_reward_hour_remaining_kwh" in text
    assert "ev_allowance_kwh_remaining" in text


def test_live_home_limits_custom_cards_and_keeps_actions_read_only() -> None:
    """The approved power-flow diagram is the only optional custom Home card."""
    home = _home()
    text = str(home)
    assert "perform-action" not in text
    assert "call-service" not in text

    def visit(cards: list[dict]) -> list[str]:
        custom = []
        for card in cards:
            kind = card["type"]
            if kind.startswith("custom:"):
                custom.append(kind)
            if "tap_action" in card:
                assert card["tap_action"] == {"action": "more-info"}
            if kind in ("grid", "vertical-stack"):
                custom.extend(visit(card["cards"]))
        return custom

    assert visit(home["cards"]) == ["custom:power-flow-card-plus"]


def test_home_markdown_templates_have_valid_jinja_syntax() -> None:
    env = Environment(autoescape=False)
    home = _home()

    def check(cards: list[dict]) -> None:
        for card in cards:
            if card["type"] == "markdown":
                env.parse(card["content"])
            elif card["type"] in ("grid", "vertical-stack"):
                check(card["cards"])

    check(home["cards"])
