"""Regression coverage for Alpha7.43 Power Down and Weekend Happy Hour planning."""

from __future__ import annotations

import ast
import json
import runpy
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
EVENTS = KEMS / "agile_alpha743_event_priority.py"
HAPPY = KEMS / "happy_hour.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
INIT = KEMS / "__init__.py"
SELECT = KEMS / "select.py"
SWITCH = KEMS / "switch.py"
DATETIME = KEMS / "datetime.py"
DOC = ROOT / "docs" / "alpha743-power-down-happy-hour.md"


def test_alpha743_release_version_keeps_web20_and_panel7() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    version = str(manifest["version"])
    assert version.startswith("0.7.0-alpha7.")
    assert int(version.rsplit(".", 1)[-1]) >= 43
    assert bundle["components"]["property_web"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["pi_agent"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["public_web"]["version"] == "0.7.0-alpha7-web.20"
    assert bundle["components"]["panel"]["version"] == "0.7.0-alpha7-panel7"


def test_alpha743_modules_parse_and_install_last() -> None:
    for path in (EVENTS, HAPPY, DATETIME):
        ast.parse(path.read_text(encoding="utf-8"))

    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha743_event_priority_patch" in loader
    assert loader.rindex("install_alpha743_event_priority_patch()") > loader.rindex(
        "install_alpha742_live_graph_telemetry_patch()"
    )


def test_manual_happy_hour_event_is_source_neutral_and_capped_per_reward() -> None:
    module = runpy.run_path(str(HAPPY))
    build = module["manual_happy_hour_event"]

    start = datetime(2026, 8, 23, 11, 0, tzinfo=UTC)
    one = build(
        {
            "weekend_happy_hour_enabled": True,
            "weekend_happy_hour_start": start.isoformat(),
            "weekend_happy_hour_duration_hours": 1,
        }
    )
    two = build(
        {
            "weekend_happy_hour_enabled": True,
            "weekend_happy_hour_start": start.isoformat(),
            "weekend_happy_hour_duration_hours": 2,
        }
    )

    assert one["source"] == "manual"
    assert one["fair_use_cap_kwh"] == 16.0
    assert (one["end"] - one["start"]).total_seconds() == 3600
    assert two["fair_use_cap_kwh"] == 32.0
    assert (two["end"] - two["start"]).total_seconds() == 7200


def test_power_down_is_absolute_priority_over_agile_price() -> None:
    source = EVENTS.read_text(encoding="utf-8")

    assert '"priority": "absolute_over_agile_price"' in source
    assert '"agile_price_can_override": False' in source
    assert '"solar_forecast_required_for_reserve": False' in source
    assert '"maximise_safe_export": True' in source
    assert '"ev_charging_allowed_during_event": False' in source
    assert '"mode": "power_down_session"' in source
    assert "house first, then maximum safe export" in source
    assert "_apply_power_down_to_plan" in source


def test_happy_hour_uses_best_known_pre_event_slots_and_reoptimises_afterwards() -> (
    None
):
    source = EVENTS.read_text(encoding="utf-8")

    assert "_candidate_prep_slots" in source
    assert '"happy_hour_headroom_preparation": True' in source
    assert (
        '"unknown_price_policy": "never guess a pre/post Happy Hour Agile price"'
        in source
    )
    assert "best_known_post_happy_hour_export_slot" in source
    assert "happy_hour_adjusted_soc_percent" in source
    assert '"mode": "happy_hour_charge"' in source
    assert '"battery_export_target_kw": 0.0' in source
    assert '"battery_discharge_target_kw": 0.0' in source


def test_alpha743_priority_order_and_hardware_boundary_are_explicit() -> None:
    source = EVENTS.read_text(encoding="utf-8")

    assert "safety > Power Down > Happy Hour > Agile price" in source
    assert '"hardware_writes": "blocked"' in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source


def test_happy_hour_manual_controls_are_shipped_on_agile_dashboard() -> None:
    event_source = EVENTS.read_text(encoding="utf-8")
    init_source = INIT.read_text(encoding="utf-8")
    select_source = SELECT.read_text(encoding="utf-8")
    switch_source = SWITCH.read_text(encoding="utf-8")

    assert DATETIME.is_file()
    assert "Platform.DATETIME" in init_source
    assert "KEMSWeekendHappyHourDurationSelect" in select_source
    assert "KEMSWeekendHappyHourPlanningSwitch" in switch_source
    for entity_id in (
        "switch.kems_weekend_happy_hour_planning",
        "datetime.kems_weekend_happy_hour_start",
        "select.kems_weekend_happy_hour_duration",
        "sensor.kems_agile_happy_hour_plan",
        "sensor.kems_agile_power_down_priority",
    ):
        assert entity_id in event_source


def test_alpha743_documentation_records_event_contract() -> None:
    source = DOC.read_text(encoding="utf-8")

    assert "0.7.0-alpha7.43" in source
    assert "Power Down is an absolute priority" in source
    assert "Weekend Happy Hour" in source
    assert "16 kWh" in source
    assert "known Agile prices" in source
    assert "Real FoxESS hardware writes remain blocked" in source
