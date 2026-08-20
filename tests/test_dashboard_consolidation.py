"""Regression tests for the simplified Alpha7.35 KEMS dashboard."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "custom_components" / "kems" / "dashboard_consolidation.py"
MASTER = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"
AGILE = ROOT / "custom_components" / "kems" / "kems_agile_smart_export_dashboard.yaml"
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
    """Mirror the current base/Agile merge and add the runtime live Agile view."""
    master = MASTER.read_text(encoding="utf-8").rstrip()
    agile = AGILE.read_text(encoding="utf-8")
    marker = "\nviews:\n"
    assert marker in agile
    agile_views = agile.split(marker, 1)[1].lstrip("\n").rstrip()
    live_view = """
  - title: Agile Smart Export
    path: agile-smart-export
    icon: mdi:transmission-tower-export
    cards:
      - type: markdown
        content: |
          Runtime Agile live scenario placeholder for consolidation testing.
""".rstrip()
    return f"{master}\n\n{agile_views}\n\n{live_view}\n"


def test_consolidated_dashboard_has_nine_simple_navigation_pages() -> None:
    """The managed UI should expose only the agreed product navigation."""
    module = _load_module()
    rendered = module.consolidate_dashboard(_assembled_source())
    parsed = yaml.safe_load(rendered)
    assert parsed["title"] == "KEMS Master Dashboard"
    assert [view["path"] for view in parsed["views"]] == EXPECTED_PATHS
    assert len(parsed["views"]) == 9


def test_every_legacy_source_view_is_preserved_under_a_product_or_advanced_page() -> (
    None
):
    """Simplification must reorganise rich data rather than delete it."""
    module = _load_module()
    source_views = module._split_views(_assembled_source())
    assert set(source_views) == module.EXPECTED_SOURCE_TITLES

    merged_sources = {
        title for spec in module.FINAL_VIEW_SPECS for title in spec.sources
    }
    assert merged_sources == module.EXPECTED_SOURCE_TITLES


def test_user_product_pages_have_live_vs_simulated_side_by_side() -> None:
    """Every optimising product should put live and simulated data together."""
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


def test_comparison_page_contains_all_four_types_and_common_metrics() -> None:
    """One page must make the four product outcomes directly comparable."""
    module = _load_module()
    parsed = yaml.safe_load(module.consolidate_dashboard(_assembled_source()))
    views = {view["path"]: str(view) for view in parsed["views"]}
    compare = views["compare"]

    for label in ("Live Data", "Battery & Solar", "Full KEMS", "Full KEMS Agile"):
        assert label in compare
    for metric in (
        "House load kW",
        "Grid import kW",
        "Grid export kW",
        "Battery → home kW",
        "Battery → export kW",
        "Total / economic cost p",
        "Grid import kWh",
        "Grid export kWh",
        "Ending SOC %",
    ):
        assert metric in compare
    assert "Cost comparison — 24 hours" in compare


def test_engineering_scenarios_are_moved_to_advanced_lab() -> None:
    """Virtual stress scenarios remain available without cluttering normal UX."""
    module = _load_module()
    parsed = yaml.safe_load(module.consolidate_dashboard(_assembled_source()))
    views = {view["path"]: str(view) for view in parsed["views"]}
    assert "select.kems_virtual_scenario" in views["advanced"]
    assert "Observe → Simulate → Shadow → Control" in views["advanced"]
    assert "select.kems_virtual_scenario" not in views["home"]


def test_consolidation_is_installed_before_runtime_routing_patches() -> None:
    """Dashboard assembly remains complete before late reporting wrappers install."""
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
