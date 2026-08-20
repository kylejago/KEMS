"""Regression coverage for Alpha7.36 Panel6 and comparison finance parity."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_alpha736_release_and_panel6_versions_are_aligned() -> None:
    """Core, bundle, verifier and ESPHome source must target Alpha7.36/Panel6."""
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    panel_py = (KEMS / "panel.py").read_text(encoding="utf-8")
    panel_yaml = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")

    assert manifest["version"] == "0.7.0-alpha7.36"
    assert bundle["components"]["panel"]["version"] == "0.7.0-alpha7-panel6"
    assert 'PANEL_CONFIG_VERSION = "0.7.0-alpha7-panel6"' in panel_py
    assert 'panel_config_version: "0.7.0-alpha7-panel6"' in panel_yaml
    assert bundle["maintenance"]["affected_components"] == [
        "kems_core",
        "dashboard",
        "panel",
    ]


def test_alpha736_panel_flow_comes_from_final_current_routing_snapshot() -> None:
    """Panel flow must mirror the same coherent Agile route used by the dashboard."""
    source = (KEMS / "agile_alpha736_panel_flow.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert 'state.get("current_routing_snapshot")' in source
    assert '"sensor.kems_panel_full_kems_agile_flow_now"' in source
    assert '"sensor.kems_agile_smart_export_flow_now"' in source
    assert 'live_attributes["simulated_soc_percent"]' in source
    assert "H=-1,S=-1,GI=-1,GE=-1" in source
    assert "safe_to_write_hardware = True" not in source
    assert ".services.async_call(" not in source


def test_alpha736_panel_selector_matches_four_user_product_types() -> None:
    """Panel6 must no longer expose the old strategy/scenario clutter."""
    source = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")
    options = re.search(r"    options:\n(?P<body>(?:      - .*\n)+)", source)
    assert options is not None
    assert options.group("body").splitlines() == [
        '      - "Live Data"',
        '      - "Battery & Solar"',
        '      - "Full KEMS"',
        '      - "Full KEMS Agile"',
    ]
    assert 'display_mode == "Battery & Solar"' in source
    assert 'display_mode == "Full KEMS"' in source
    assert 'display_mode == "Full KEMS Agile"' in source
    assert "scenario_agile_flow: sensor.kems_panel_full_kems_agile_flow_now" in source


def test_alpha736_dashboard_repairs_missing_compare_values_and_adds_finance() -> None:
    """Compare must use real period data and expose winner/ROI history."""
    source = (KEMS / "dashboard_alpha736_finance.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "sensor.kems_today_energy_summary" in source
    assert "import_cost_pence" in source
    assert "current_routing_snapshot" in source
    assert "Awaiting battery data" in source
    assert "Awaiting solar data" in source
    assert "Winner by period" in source
    assert "Last 7 days" in source
    assert "Last 30 days" in source
    assert "Rolling 365 evidence" in source
    assert "All tracked Agile evidence" in source
    assert "title: Cost & ROI" in source
    assert "Actual vs core KEMS simulation" in source
    assert "sensor.kems_actual_roi" in source
    assert "sensor.kems_actual_system_value_total" in source
    assert "sensor.kems_lifetime_simulated_system_value" in source


def test_alpha736_reporting_patches_install_after_alpha735() -> None:
    """The new reporting layers must not disturb the proven dispatch ordering."""
    runtime = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")
    assert runtime.rindex("install_alpha736_panel_flow_patch()") > runtime.rindex(
        "install_alpha735_cheap_handover_patch()"
    )
    assert runtime.rindex(
        "install_alpha736_finance_dashboard_patch()"
    ) > runtime.rindex("install_alpha736_panel_flow_patch()")
    assert "alpha736_optimizer" not in runtime
