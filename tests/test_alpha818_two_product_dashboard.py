"""Regression coverage for Alpha8.18 two-product dashboard presentation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import yaml

ROOT = Path(__file__).parents[1]
PIPELINE_PATH = ROOT / "custom_components" / "kems" / "dashboard_pipeline.py"
CONSOLIDATION_PATH = ROOT / "custom_components" / "kems" / "dashboard_consolidation.py"
MASTER = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"
AGILE = ROOT / "custom_components" / "kems" / "kems_agile_smart_export_dashboard.yaml"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PIPELINE = _load_module("kems_dashboard_pipeline_alpha818_test", PIPELINE_PATH)
CONSOLIDATION = _load_module(
    "kems_dashboard_consolidation_alpha818_test", CONSOLIDATION_PATH
)


def _assembled_source() -> str:
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
          Runtime Agile live scenario placeholder.
""".rstrip()
    return f"{master}\n\n{agile_views}\n\n{live_view}\n"


def _final_dashboard() -> dict:
    consolidated = CONSOLIDATION.consolidate_dashboard(_assembled_source())
    final = PIPELINE.canonicalize_final_dashboard(consolidated)
    parsed = yaml.safe_load(final)
    assert isinstance(parsed, dict)
    return parsed


def test_final_navigation_has_two_products_and_restores_agile_slots() -> None:
    """Only Live Data/KEMS are products; Agile Slots remains tariff information."""
    parsed = _final_dashboard()
    paths = [view["path"] for view in parsed["views"]]

    assert "live-data" in paths
    assert "kems" in paths
    assert "agile-slots" in paths
    assert "battery-solar" not in paths
    assert "full-kems" not in paths
    assert "full-kems-agile" not in paths


def test_compare_page_is_live_data_vs_kems_only() -> None:
    """The customer comparison must never expose the retired four-engine table."""
    parsed = _final_dashboard()
    views = {view["path"]: str(view) for view in parsed["views"]}
    compare = views["compare"]

    assert "Live Data" in compare
    assert "KEMS" in compare
    assert "Battery & Solar" not in compare
    assert "Full KEMS Agile" not in compare
    assert "Compare every KEMS type" not in compare
    assert "sensor.kems_energy_cost_comparison" in compare
    assert "sensor.kems_compare_kems_no_export_cost_today" in compare
    assert "sensor.kems_compare_full_kems_forecast_cost_today" in compare
    assert "sensor.kems_agile_live_scenario" in compare


def test_agile_slots_preserves_today_and_tomorrow_half_hour_tables() -> None:
    """The useful Agile slot list must survive retirement of the Agile product tab."""
    parsed = _final_dashboard()
    views = {view["path"]: str(view) for view in parsed["views"]}
    slots = views["agile-slots"]

    assert "not a separate KEMS product" in slots
    assert "Today — actual Region L Agile prices and Smart Export plan" in slots
    assert "Tomorrow — published prices and forecast plan" in slots
    assert "today_slots" in slots
    assert "tomorrow_slots" in slots


def test_managed_history_does_not_reintroduce_legacy_strategy_comparisons() -> None:
    """Internal Agile strategy history stays outside the normal managed dashboard."""
    parsed = _final_dashboard()
    views = {view["path"]: str(view) for view in parsed["views"]}

    assert "Agile History" not in views["history"]


def test_alpha818_scope_keeps_web_panel_and_hardware_boundary_unchanged() -> None:
    """This is a Home Assistant dashboard-only hotfix."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    content = PIPELINE_PATH.read_text(encoding="utf-8")

    assert manifest["version"] == "0.8.0-alpha8.18"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.4"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.4"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.4"
    assert "real_backend" not in content
    assert "commands_permitted" not in content
