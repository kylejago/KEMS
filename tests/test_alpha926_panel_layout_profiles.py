"""Regression contract for Alpha9.26 selectable KEMS panel layouts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONST = ROOT / "custom_components" / "kems" / "const.py"
CONFIG_FLOW = ROOT / "custom_components" / "kems" / "config_flow.py"
SELECT = ROOT / "custom_components" / "kems" / "select.py"
PANEL = ROOT / "custom_components" / "kems" / "kems16x16.yaml"
PANEL_HEALTH = ROOT / "custom_components" / "kems" / "panel.py"
DASHBOARD = ROOT / "dashboards" / "kems_master_dashboard.yaml"
PACKAGED_DASHBOARD = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def test_alpha926_exposes_v1_v2_panel_layout_setting_with_v1_default() -> None:
    """Existing panels default to V1 while Settings and live select expose V2."""
    const = CONST.read_text(encoding="utf-8")
    config = CONFIG_FLOW.read_text(encoding="utf-8")
    select = SELECT.read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")

    assert 'CONF_PANEL_LAYOUT = "panel_layout"' in const
    assert 'PANEL_LAYOUT_V1 = "v1"' in const
    assert 'PANEL_LAYOUT_V2 = "v2"' in const
    assert "CONF_PANEL_LAYOUT: PANEL_LAYOUT_V1" in const
    assert '"panel": "Panel display"' in config
    assert "PANEL_SCHEMA" in config
    assert "CONF_PANEL_LAYOUT" in config
    assert "KEMSPanelLayoutSelect" in select
    assert '"V1 — Current"' in select
    assert '"V2 — Inverter centred"' in select
    assert "select.kems_panel_layout" in dashboard


def test_alpha926_panel_firmware_subscribes_to_kems_layout_and_keeps_v1() -> None:
    """One firmware image must render either profile without losing V1."""
    panel = PANEL.read_text(encoding="utf-8")

    assert "panel_layout: select.kems_panel_layout" in panel
    assert "id: ha_panel_layout" in panel
    assert "entity_id: ${panel_layout}" in panel
    assert 'const bool layout_v2 = panel_layout == "V2 — Inverter centred";' in panel
    assert "if (layout_v2)" in panel

    # V1's established central-hub geometry remains present.
    assert "rect(7, 7, 10, 10, RAINBOW);" in panel
    assert "flow_horizontal(3, 8, 6, 9" in panel
    assert "flow_horizontal(11, 8, 14, 9" in panel


def test_alpha926_v2_matches_inverter_centred_16x16_faceplate() -> None:
    """V2 maps Grid/Solar/Battery -> Inverter -> Home/EV on the new face."""
    panel = PANEL.read_text(encoding="utf-8")

    assert "// V2: inverter-centred faceplate." in panel
    assert "rect(4, 8, 13, 9, RAINBOW);" in panel
    assert "flow_vertical(4, 3, 5, 7" in panel   # Grid <-> inverter
    assert "flow_vertical(8, 3, 9, 7" in panel   # Solar -> inverter
    assert "flow_vertical(12, 3, 13, 7" in panel  # Battery <-> inverter
    assert "flow_vertical(5, 10, 6, 14" in panel  # Inverter -> home
    assert "flow_vertical(11, 10, 12, 14" in panel  # Inverter -> EV

    # Exact 90-degree counter-clockwise rotation of the V1 ten-cell map.
    assert "const int battery_v2_cols[10] = {16, 16, 15, 15, 14, 14, 13, 13, 12, 12};" in panel
    assert "const int battery_v2_rows[10] = {2, 1, 2, 1, 2, 1, 2, 1, 2, 1};" in panel

    # The inverter keeps the established slow 40-second colour fade.
    assert "float rainbow_hue = fmodf((float) now / 40000.0f, 1.0f);" in panel


def test_alpha926_versions_and_bundle_are_coordinated() -> None:
    """Core, managed panel and coordinated bundle must advertise the new targets."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    panel = PANEL.read_text(encoding="utf-8")
    panel_health = PANEL_HEALTH.read_text(encoding="utf-8")

    assert manifest["version"] == "0.9.0-alpha9.26"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.1"
    assert 'panel_config_version: "0.9.0-alpha9-panel.1"' in panel
    assert 'PANEL_CONFIG_VERSION = "0.9.0-alpha9-panel.1"' in panel_health


def test_alpha926_dashboard_source_and_packaged_copy_remain_identical() -> None:
    """Adding the panel selector must keep the managed dashboard package current."""
    assert DASHBOARD.read_bytes() == PACKAGED_DASHBOARD.read_bytes()
