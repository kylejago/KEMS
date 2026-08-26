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


def test_today_and_tomorrow_are_single_readable_chronological_lists() -> None:
    parsed = _final_dashboard()

    today = _card(_view(parsed, "kems"), "Today's KEMS plan — 00:00 to 23:30")
    tomorrow = _card(_view(parsed, "tomorrow"), "Tomorrow's KEMS plan — 00:00 to 23:30")

    for card in (today, tomorrow):
        assert card["type"] == "markdown"
        content = card["content"]
        assert "| Time | KEMS plan |" in content
        assert "| Time | Rate | KEMS plan and energy |" not in content
        assert "{% for p in slots %}" in content
        assert "House first — no battery export planned" in content
        assert "Battery export" in content
        assert "current plan snapshot" in content
        assert "Grid in/out" not in content

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


def test_rolling_hold_is_explained_as_a_decision_not_an_error() -> None:
    module = _pipeline_module()
    content = module._finalise_dashboard_bytes(SOURCE.read_bytes()).decode("utf-8")

    assert "{% if 'hold' in rolling %}" in content
    assert "House first — no battery export planned" in content
    assert "not a waiting/error state" in content
    assert "hold — rolling replan" not in content


def test_nullable_slot_values_do_not_break_plan_rows() -> None:
    module = _pipeline_module()
    content = module._finalise_dashboard_bytes(SOURCE.read_bytes()).decode("utf-8")

    for alias, field in (
        ("gi", "grid_import_kwh"),
        ("bo", "battery_export_kwh"),
        ("soc", "ending_soc_percent"),
    ):
        assert f"set {alias} = p.get('{field}')" in content

    assert "p.get('rate_pence') is not none else 'Rate —'" in content
    assert "planned_export is not none" in content


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


def test_finaliser_leaves_home_view_semantically_unchanged() -> None:
    source = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    final = _final_dashboard()
    assert _view(final, "home") == _view(source, "home")


def test_finaliser_is_idempotent() -> None:
    module = _pipeline_module()
    once = module._finalise_dashboard_bytes(SOURCE.read_bytes())
    twice = module._finalise_dashboard_bytes(once)
    assert twice == once
