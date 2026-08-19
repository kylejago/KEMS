"""Regression guards for the managed-panel release introduced in KEMS alpha7.21."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_managed_panel_packaged_and_health_versions_remain_aligned() -> None:
    """Later KEMS alphas must keep the packaged panel and verifier in lockstep."""
    panel = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")
    health = (KEMS / "panel.py").read_text(encoding="utf-8")

    panel_match = re.search(r'panel_config_version: "([^"]+)"', panel)
    health_match = re.search(r'PANEL_CONFIG_VERSION = "([^"]+)"', health)
    assert panel_match is not None
    assert health_match is not None
    panel_version = panel_match.group(1)
    health_version = health_match.group(1)
    assert panel_version == health_version
    assert panel_version.startswith("0.7.0-alpha7-panel")
    assert int(panel_version.rsplit("panel", 1)[1]) >= 4


def test_alpha721_panel_uses_a_true_ten_cell_battery_meter() -> None:
    panel = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")

    assert "Ten physical battery cells: 10% per cell" in panel
    assert "const int battery_cols[10]" in panel
    assert "const int battery_rows[10] = {11, 11, 10, 10, 9, 9, 8, 8, 7, 7};" in panel
    assert "const int full_cells = (int) floorf(soc / 10.0f);" in panel
    assert "rect(15, 7, 16, 8, pulse(GREEN));" not in panel


def test_alpha721_preserves_agile_panel_scenario() -> None:
    panel = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")

    assert '- "Agile Smart Export"' in panel
    assert "sensor.kems_agile_smart_export_cost_today" in panel
    assert "sensor.kems_agile_smart_export_flow_now" in panel
    assert "sensor.kems_compare_solar_and_battery_flow_now" in panel
