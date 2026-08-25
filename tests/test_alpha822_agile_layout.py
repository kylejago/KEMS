"""Alpha8.22 regressions for the managed Today/Tomorrow plan layout."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PIPELINE = ROOT / "custom_components" / "kems" / "dashboard_pipeline.py"


def _pipeline_module():
    spec = importlib.util.spec_from_file_location("kems_dashboard_pipeline_test", PIPELINE)
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


def _plan_grid(view: dict, prefix: str) -> dict:
    expected = [
        f"{prefix} — 00:00 to 07:30",
        f"{prefix} — 08:00 to 15:30",
        f"{prefix} — 16:00 to 23:30",
    ]
    for card in view["cards"]:
        if not isinstance(card, dict) or card.get("type") != "grid":
            continue
        titles = [item.get("title") for item in card.get("cards", [])]
        if titles == expected:
            return card
    raise AssertionError(f"No ordered {prefix} plan grid found")


def test_today_and_tomorrow_plans_are_fixed_chronological_grids() -> None:
    parsed = _final_dashboard()

    today = _plan_grid(_view(parsed, "kems"), "Today")
    tomorrow = _plan_grid(_view(parsed, "tomorrow"), "Tomorrow")

    assert today["columns"] == 3
    assert today["square"] is False
    assert tomorrow["columns"] == 3
    assert tomorrow["square"] is False

    for path, prefix in (("kems", "Today —"), ("tomorrow", "Tomorrow —")):
        top_level_titles = [
            card.get("title")
            for card in _view(parsed, path)["cards"]
            if isinstance(card, dict)
        ]
        assert not any(str(title).startswith(prefix) for title in top_level_titles)


def test_nullable_slot_values_render_as_dash_instead_of_breaking_card() -> None:
    module = _pipeline_module()
    content = module._finalise_dashboard_bytes(SOURCE.read_bytes()).decode("utf-8")

    for field in ("grid_import_kwh", "grid_export_kwh", "battery_export_kwh"):
        assert f"p.get('{field}', 0) | float" not in content
        assert f"p.get('{field}') is not none else '—'" in content

    assert "p.get('ending_soc_percent') is not none else '—'" in content


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
