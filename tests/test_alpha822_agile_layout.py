"""Regressions for the managed Today/Tomorrow plan presentation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

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


def test_today_and_tomorrow_are_single_chronological_flow_tables() -> None:
    parsed = _final_dashboard()

    today = _card(_view(parsed, "kems"), "Today's KEMS plan — 00:00 to 23:30")
    tomorrow = _card(_view(parsed, "tomorrow"), "Tomorrow's KEMS plan — 00:00 to 23:30")

    for card in (today, tomorrow):
        assert card["type"] == "markdown"
        content = card["content"]
        assert "| Time | Price | Est. SOC | Grid | Solar | Battery |" in content
        assert "{% for p in slots %}" in content
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

    assert "**{{ ga }}**<br>" in content
    assert "**{{ sa }}**<br>" in content
    assert "**{{ ba }}**<br>" in content
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
