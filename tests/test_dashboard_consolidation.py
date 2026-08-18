"""Regression tests for the production-style KEMS dashboard consolidation."""

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
    "live",
    "plan",
    "agile",
    "compare",
    "history",
    "battery-solar",
    "ev-tariff",
    "eps",
    "control",
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


def test_consolidated_dashboard_has_exactly_eleven_navigation_pages() -> None:
    """The managed UI should expose only the agreed production navigation."""
    module = _load_module()
    rendered = module.consolidate_dashboard(_assembled_source())
    parsed = yaml.safe_load(rendered)
    assert parsed["title"] == "KEMS Master Dashboard"
    assert [view["path"] for view in parsed["views"]] == EXPECTED_PATHS
    assert len(parsed["views"]) == 11


def test_every_legacy_source_view_is_preserved_or_intentionally_replaced() -> None:
    """Consolidation must not silently lose one of the existing feature tabs."""
    module = _load_module()
    source_views = module._split_views(_assembled_source())
    assert set(source_views) == module.EXPECTED_SOURCE_TITLES

    merged_sources = {
        title for spec in module.FINAL_VIEW_SPECS for title in spec.sources
    }
    assert module.EXPECTED_SOURCE_TITLES - merged_sources == {"Control & EPS"}


def test_consolidated_dashboard_keeps_live_preparation_and_eps_pages() -> None:
    """The new navigation should prepare the same UI for future live hardware."""
    module = _load_module()
    parsed = yaml.safe_load(module.consolidate_dashboard(_assembled_source()))
    rendered = str(parsed)
    assert "SIMULATION / PRE-INSTALL" in rendered
    assert "Actual hardware" in rendered
    assert "KEMS target" in rendered
    assert "Simulation → Shadow → Live" in rendered
    assert "If the grid failed now" in rendered
    assert "sensor.kems_estimated_outage_runtime" in rendered
    assert "sensor.kems_desired_battery_export_power" in rendered


def test_related_pages_are_merged_without_old_navigation_paths() -> None:
    """Forecast, Agile, history and system detail should be grouped as intended."""
    module = _load_module()
    parsed = yaml.safe_load(module.consolidate_dashboard(_assembled_source()))
    views = {view["path"]: str(view) for view in parsed["views"]}

    assert "Full KEMS Forecast" in views["plan"]
    assert "Simulation" in views["plan"]
    assert "Agile Price Plan" in views["agile"]
    assert "Agile Assumptions" in views["agile"]
    assert "Forecast vs Agile" in views["compare"]
    assert "Agile History" in views["history"]
    assert "Gas" in views["history"]
    assert "Power Down" in views["ev-tariff"]
    assert "Updates" in views["system"]
    assert "All Entities" in views["system"]


def test_consolidation_is_installed_after_all_agile_dashboard_patches() -> None:
    """The final writer must consolidate only after feature views are complete."""
    runtime = RUNTIME.read_text(encoding="utf-8")
    assert "install_live_scenario_patch()\ninstall_dashboard_yaml_guard()" in runtime
    assert (
        "install_alpha717_dashboard_patch()\ninstall_alpha719_validation_patch()"
        in runtime
    )
    assert (
        "install_alpha719_validation_patch()\n"
        "install_dashboard_consolidation()\n"
        "install_alpha719_dashboard_patch()"
    ) in runtime
