"""Regressions for the managed Today/Tomorrow plan presentation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PIPELINE = ROOT / "custom_components" / "kems" / "dashboard_pipeline.py"


def _pipeline_module():
    spec = importlib.util.spec_from_file_location(
        "kems_dashboard_pipeline_test", PIPELINE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _final_dashboard() -> dict:
    module = _pipeline_module()
    payload = module._finalise_dashboard_bytes(SOURCE.read_bytes())
    parsed = yaml.safe_load(payload.decode("utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def _view(parsed: dict, path: str) -> dict:
    return next(view for view in parsed["views"] if view["path"] == path)


def _card(view: dict, title: str) -> dict:
    return next(card for card in view["cards"] if card.get("title") == title)


def _stack_card(stack: dict, title: str) -> dict:
    return next(card for card in stack["cards"] if card.get("title") == title)


def test_agile_plan_is_a_native_full_width_panel_view() -> None:
    parsed = _final_dashboard()
    agile = _view(parsed, "agile-plan")

    assert agile["title"] == "Agile Plan"
    assert agile["icon"] == "mdi:table-large"
    assert agile["type"] == "panel"
    assert len(agile["cards"]) == 1

    stack = agile["cards"][0]
    assert stack["type"] == "vertical-stack"
    assert len(stack["cards"]) == 3
    assert stack["cards"][0]["type"] == "markdown"
    assert "# Agile Plan" in stack["cards"][0]["content"]
    assert "Full-width" in stack["cards"][0]["content"]


def test_today_and_tomorrow_are_full_width_chronological_flow_tables() -> None:
    parsed = _final_dashboard()
    agile = _view(parsed, "agile-plan")
    stack = agile["cards"][0]

    today = _stack_card(stack, "Today's KEMS plan — 00:00 to 23:30")
    tomorrow = _stack_card(stack, "Tomorrow's KEMS plan — 00:00 to 23:30")

    for card in (today, tomorrow):
        assert card["type"] == "markdown"
        content = card["content"]
        assert "| Time | Price | Est. SOC | Grid | Solar | Battery |" in content
        assert "{%- for p in slots %}" in content
        assert "flow_estimated_soc_percent" in content
        assert "flow_grid_action" in content
        assert "flow_grid_kwh" in content
        assert "flow_solar_action" in content
        assert "flow_solar_kwh" in content
        assert "flow_battery_action" in content
        assert "flow_battery_kwh" in content
        assert "current KEMS plan snapshot" in content
        assert "half-hour" in content
        assert "| Time | KEMS plan |" not in content
        assert "<br>" not in content
        assert "%}}" not in content
        assert "**{{ ga }}** ·" in content
        assert "**{{ sa }}** ·" in content
        assert "**{{ ba }}** ·" in content

    final_text = yaml.safe_dump(parsed, sort_keys=False)
    for old_title in (
        "Today — 00:00 to 07:30",
        "Today — 08:00 to 15:30",
        "Today — 16:00 to 23:30",
        "Tomorrow — 00:00 to 07:30",
        "Tomorrow — 08:00 to 15:30",
        "Tomorrow — 16:00 to 23:30",
    ):
        assert old_title not in final_text


def test_rendered_agile_rows_remain_inside_one_markdown_table() -> None:
    parsed = _final_dashboard()
    agile = _view(parsed, "agile-plan")
    stack = agile["cards"][0]
    today = _stack_card(stack, "Today's KEMS plan — 00:00 to 23:30")
    slots = [
        {
            "label": "16:30",
            "rate_pence": 23.57,
            "flow_estimated_soc_percent": 68.7,
            "flow_grid_action": "EXPORT",
            "flow_grid_kwh": 3.90,
            "flow_solar_action": "HOME/EXPO",
            "flow_solar_kwh": 2.30,
            "flow_battery_action": "EXPORT",
            "flow_battery_kwh": 2.10,
        },
        {
            "label": "17:00",
            "rate_pence": 23.93,
            "flow_estimated_soc_percent": 64.0,
            "flow_grid_action": "EXPORT",
            "flow_grid_kwh": 2.85,
            "flow_solar_action": "HOME",
            "flow_solar_kwh": 0.45,
            "flow_battery_action": "EXPORT",
            "flow_battery_kwh": 2.85,
        },
    ]

    def state_attr(entity_id: str, attribute: str):
        assert entity_id == "sensor.kems_agile_slots"
        return slots if attribute == "today_slots" else []

    rendered = Environment(autoescape=False).from_string(today["content"]).render(
        state_attr=state_attr
    )
    expected_table = (
        "| Time | Price | Est. SOC | Grid | Solar | Battery |\n"
        "|---|---:|---:|---|---|---|\n"
        "| 16:30 | 23.57p | 68.7% | **EXPORT** · 3.90 kWh | "
        "**HOME/EXPORT** · 2.30 kWh | **EXPORT** · 2.10 kWh |\n"
        "| 17:00 | 23.93p | 64.0% | **EXPORT** · 2.85 kWh | "
        "**HOME** · 0.45 kWh | **EXPORT** · 2.85 kWh |"
    )

    assert expected_table in rendered
    assert "\n\n| 16:30" not in rendered
    assert "|---|---:|---:|---|---|---|\n| 16:30" in rendered
    assert "2.30 kWh" in rendered
    assert "2.10 kWh" in rendered
    assert "3.90 kWh" in rendered
    assert "HOME/EXPO" not in rendered


def test_kems_page_keeps_only_a_compact_now_next_plan_summary() -> None:
    parsed = _final_dashboard()
    kems = _view(parsed, "kems")
    summary = _card(kems, "Current and next Agile slots")

    assert summary["type"] == "markdown"
    content = summary["content"]
    assert "'NOW' if loop.index0 == 0 else 'NEXT'" in content
    assert "flow_estimated_soc_percent" in content
    assert "flow_grid_action" in content
    assert "flow_solar_action" in content
    assert "flow_battery_action" in content
    assert "%}}" not in content
    assert "Use the **Agile Plan** tab" in content
    assert not any(
        card.get("title") == "Today's KEMS plan — 00:00 to 23:30"
        for card in kems["cards"]
    )


def test_tomorrow_page_points_to_full_width_agile_plan() -> None:
    parsed = _final_dashboard()
    tomorrow = _view(parsed, "tomorrow")
    pointer = _card(tomorrow, "Agile half-hour plan")

    assert pointer["type"] == "markdown"
    assert "**Agile Plan** tab" in pointer["content"]
    assert "full dashboard width" in pointer["content"]
    assert not any(
        card.get("title") == "Tomorrow's KEMS plan — 00:00 to 23:30"
        for card in tomorrow["cards"]
    )


def test_flow_table_uses_canonical_route_labels_and_energy_totals() -> None:
    module = _pipeline_module()
    content = module._finalise_dashboard_bytes(SOURCE.read_bytes()).decode("utf-8")

    for field in (
        "flow_grid_action",
        "flow_grid_kwh",
        "flow_solar_action",
        "flow_solar_kwh",
        "flow_battery_action",
        "flow_battery_kwh",
        "flow_estimated_soc_percent",
    ):
        assert f"p.get('{field}')" in content

    assert "replace('EXPO', 'EXPORT')" in content
    assert "%}}" not in content
    assert "**{{ ga }}** ·" in content
    assert "**{{ sa }}** ·" in content
    assert "**{{ ba }}** ·" in content
    assert "%.2f kWh" in content
    assert "%.1f%%" in content


def test_table_does_not_rederive_routing_from_legacy_slot_fields() -> None:
    module = _pipeline_module()
    content = module._finalise_dashboard_bytes(SOURCE.read_bytes()).decode("utf-8")

    assert "rolling_planned_battery_export_kwh" not in content
    assert "House first — no battery export planned" not in content
    assert "{% if 'hold' in rolling %}" not in content


def test_tomorrow_partial_publication_is_visible_and_aggregation_is_safe() -> None:
    module = _pipeline_module()
    content = module._finalise_dashboard_bytes(SOURCE.read_bytes()).decode("utf-8")

    assert "Awaiting publication" in content
    assert "s.attributes.tomorrow_missing_labels" in content
    for field in (
        "grid_import_kwh",
        "grid_export_kwh",
        "battery_export_kwh",
        "rate_pence",
    ):
        assert f"p.get('{field}') | float(0)" in content


def test_finaliser_preserves_home_except_named_financial_summary() -> None:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    final = _final_dashboard()
    source_home = _view(source, "home")
    final_home = _view(final, "home")

    assert {key: value for key, value in final_home.items() if key != "cards"} == {
        key: value for key, value in source_home.items() if key != "cards"
    }
    assert len(final_home["cards"]) == len(source_home["cards"])

    changed = 0
    for source_card, final_card in zip(
        source_home["cards"], final_home["cards"], strict=True
    ):
        if source_card.get("title") == "Today — Live Data vs KEMS":
            changed += 1
            assert final_card["title"] == source_card["title"]
            assert final_card["type"] == source_card["type"]
            assert final_card["content"] != source_card["content"]
            assert "sensor.kems_energy_cost_comparison" in final_card["content"]
            assert "total_energy_cost_pence" in final_card["content"]
            continue
        assert final_card == source_card

    assert changed == 1


def test_finaliser_is_idempotent() -> None:
    module = _pipeline_module()
    once = module._finalise_dashboard_bytes(SOURCE.read_bytes())
    twice = module._finalise_dashboard_bytes(once)
    assert twice == once
