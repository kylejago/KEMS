"""Regression coverage for the managed Agile dashboard YAML guard."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
GUARD = ROOT / "custom_components" / "kems" / "agile_dashboard_yaml_guard.py"


def _guard_module():
    spec = importlib.util.spec_from_file_location(
        "kems_agile_dashboard_yaml_guard", GUARD
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_guard_repairs_agile_view_into_top_level_views_list() -> None:
    """A root-level Agile list item must be re-indented under views."""
    module = _guard_module()
    broken = b"""title: KEMS Master Dashboard
views:
  - title: Existing
    path: existing
    cards: []

- title: Agile Smart Export
    path: agile-smart-export
    cards: []
"""
    repaired = module.repair_agile_live_view_indentation(broken)
    parsed = yaml.safe_load(repaired.decode("utf-8"))
    assert parsed["title"] == "KEMS Master Dashboard"
    assert [view["path"] for view in parsed["views"]] == [
        "existing",
        "agile-smart-export",
    ]


def test_runtime_installs_yaml_guard_after_live_view_patch() -> None:
    """The final dashboard writer must run after the Agile live view is added."""
    runtime = (
        ROOT / "custom_components" / "kems" / "agile_smart_export_runtime.py"
    ).read_text(encoding="utf-8")
    assert "install_live_scenario_patch()\ninstall_dashboard_yaml_guard()" in runtime
