"""Regression guards for the panel4 release introduced in KEMS alpha7.21."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_panel4_packaged_and_health_versions_remain_aligned() -> None:
    """Later KEMS alphas must keep the packaged panel and verifier in lockstep."""
    panel = (KEMS / "kems16x16.yaml").read_text(encoding="utf-8")
    health = (KEMS / "panel.py").read_text(encoding="utf-8")

    assert 'panel_config_version: "0.7.0-alpha7-panel4"' in panel
    assert 'PANEL_CONFIG_VERSION = "0.7.0-alpha7-panel4"' in health


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
