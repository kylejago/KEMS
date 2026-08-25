"""Regression tests for the retained internal Alpha7.35 consolidation helper."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "custom_components" / "kems" / "dashboard_consolidation.py"
RUNTIME = ROOT / "custom_components" / "kems" / "agile_smart_export_runtime.py"

EXPECTED_PATHS = [
    "home",
    "live-data",
    "battery-solar",
    "full-kems",
    "full-kems-agile",
    "compare",
    "history",
    "advanced",
    "system",
]


def _load_module():
    """Load the pure consolidation helper without importing Home Assistant."""
    spec = importlib.util.spec_from_file_location(
        "kems_dashboard_consolidation_test", MODULE_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assembled_source() -> str:
    """Build synthetic legacy source views without coupling to the customer YAML."""
    module = _load_module()
    parts = ["title: KEMS legacy engineering fixture\n\nviews:\n"]
    for index, title in enumerate(sorted(module.EXPECTED_SOURCE_TITLES)):
        parts.append(
            f"  - title: {title}\n"
            f"    path: source-{index}\n"
            "    cards:\n"
            "      - type: markdown\n"
            "        content: |\n"
            f"          Internal evidence fixture for {title}.\n"
        )
    return "\n".join(part.rstrip() for part in parts).rstrip() + "\n"


def test_consolidated_dashboard_has_nine_internal_navigation_pages() -> None:
    """The retained helper must still deterministically consolidate legacy evidence."""
    module = _load_module()
    rendered = module.consolidate_dashboard(_assembled_source())
    parsed = yaml.safe_load(rendered)
    assert parsed["title"] == "KEMS Master Dashboard"
    assert [view["path"] for view in parsed["views"]] == EXPECTED_PATHS
    assert len(parsed["views"]) == 9


def test_every_legacy_source_view_is_preserved_by_internal_helper() -> None:
    """Internal engineering consolidation must retain every legacy source view."""
    module = _load_module()
    source_views = module._split_views(_assembled_source())
    assert set(source_views) == module.EXPECTED_SOURCE_TITLES

    merged_sources = {
        title for spec in module.FINAL_VIEW_SPECS for title in spec.sources
    }
    assert merged_sources == module.EXPECTED_SOURCE_TITLES


def test_internal_product_prefixes_still_expose_engineering_evidence() -> None:
    """Legacy prefixes remain usable for standalone engineering evidence only."""
    module = _load_module()
    parsed = yaml.safe_load(module.consolidate_dashboard(_assembled_source()))
    views = {view["path"]: str(view) for view in parsed["views"]}

    assert "actual data only" in views["live-data"]
    for path in ("battery-solar", "full-kems", "full-kems-agile"):
        assert "LIVE —" in views[path]
        assert "SIMULATED —" in views[path]

    assert "sensor.kems_compare_solar_and_battery_cost_today" in views["battery-solar"]
    assert "sensor.kems_compare_full_kems_forecast_cost_today" in views["full-kems"]
    assert "sensor.kems_agile_live_scenario" in views["full-kems-agile"]


def test_internal_compare_fixture_keeps_four_engine_evidence() -> None:
    """The old four-engine comparison survives internally, not in customer YAML."""
    module = _load_module()
    parsed = yaml.safe_load(module.consolidate_dashboard(_assembled_source()))
    views = {view["path"]: str(view) for view in parsed["views"]}
    compare = views["compare"]

    for label in ("Live Data", "Battery & Solar", "Full KEMS", "Full KEMS Agile"):
        assert label in compare
    assert "Cost comparison — 24 hours" in compare


def test_engineering_scenarios_are_retained_in_internal_advanced_lab() -> None:
    """Virtual stress scenarios remain available to engineering evidence tooling."""
    module = _load_module()
    parsed = yaml.safe_load(module.consolidate_dashboard(_assembled_source()))
    views = {view["path"]: str(view) for view in parsed["views"]}
    assert "select.kems_virtual_scenario" in views["advanced"]
    assert "Observe → Simulate → Shadow → Control" in views["advanced"]


def test_historical_runtime_install_order_is_preserved_for_internal_evidence() -> None:
    """Retained runtime evidence patches keep their historical deterministic order."""
    runtime = RUNTIME.read_text(encoding="utf-8")
    assert "install_live_scenario_patch()\ninstall_dashboard_yaml_guard()" in runtime
    assert (
        "install_alpha719_validation_patch()\n"
        "install_dashboard_consolidation()\n"
        "install_alpha719_dashboard_patch()"
    ) in runtime
    assert runtime.rindex("install_alpha735_cheap_handover_patch()") > runtime.rindex(
        "install_alpha734_deadline_guard_patch()"
    )
