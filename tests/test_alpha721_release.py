"""Regression guards for the managed-panel release introduced in KEMS alpha7.21."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_managed_panel_packaged_source_matches_current_health_version() -> None:
    """Alpha8 ships the exact managed-panel target without runtime rewriting."""
    panel = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")
    health = (KEMS / "panel.py").read_text(encoding="utf-8")
    dashboard = (KEMS / "dashboard.py").read_text(encoding="utf-8")

    panel_match = re.search(r'panel_config_version: "([^"]+)"', panel)
    health_match = re.search(r'PANEL_CONFIG_VERSION = "([^"]+)"', health)
    assert panel_match is not None
    assert health_match is not None
    source_version = panel_match.group(1)
    health_version = health_match.group(1)
    assert source_version == "0.9.0-alpha9-panel.0"
    assert health_version == source_version
    assert not (KEMS / "panel_ev_policy.py").exists()
    assert "PANEL6_VERSION_LINE" not in dashboard
    assert "PANEL7_VERSION_LINE" not in dashboard
    assert "return PACKAGED_PANEL_PATH.read_bytes()" in dashboard


def test_alpha721_panel_uses_a_true_ten_cell_battery_meter() -> None:
    panel = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")

    assert "Ten physical battery cells: 10% per cell" in panel
    assert "const int battery_cols[10]" in panel
    assert "const int battery_rows[10] = {11, 11, 10, 10, 9, 9, 8, 8, 7, 7};" in panel
    assert "const int full_cells = (int) floorf(soc / 10.0f);" in panel
    assert "rect(15, 7, 16, 8, pulse(GREEN));" not in panel


def test_alpha721_preserves_agile_panel_capability() -> None:
    """Later panel UX may rename Agile, but the Agile routing capability remains."""
    panel = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")

    assert '- "Full KEMS Agile"' in panel
    assert "sensor.kems_agile_smart_export_cost_today" in panel
    assert "sensor.kems_panel_full_kems_agile_flow_now" in panel
    assert "sensor.kems_compare_solar_and_battery_flow_now" in panel
