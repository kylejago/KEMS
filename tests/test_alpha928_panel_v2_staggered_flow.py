"""Regression contracts for Alpha9.28 V2 panel staggered flow."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "custom_components" / "kems" / "kems16x16.yaml"
PANEL_HEALTH = ROOT / "custom_components" / "kems" / "panel.py"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def test_alpha928_v2_launches_next_packet_at_fourth_position_only() -> None:
    """V2 5-row links overlap packets at position four; V1 stays unchanged."""
    panel = PANEL.read_text(encoding="utf-8")

    assert "auto flow_vertical_v2_dual" in panel
    assert "auto flow_vertical_v2" in panel
    assert "const int launch_spacing =" in panel
    assert "flow_vertical_v2_dual" in panel

    v2 = panel.split("if (layout_v2) {", 1)[1].split("return;", 1)[0]
    assert "flow_vertical_v2(4, 3, 5, 7" in v2
    assert "flow_vertical_v2(8, 3, 9, 7" in v2
    assert "flow_vertical_v2(12, 3, 13, 7" in v2
    assert "flow_vertical_v2(5, 10, 6, 14" in v2
    assert "flow_vertical_v2(11, 10, 12, 14" in v2
    assert "flow_vertical_v2_dual(" in v2

    # The established V1 2x4 paths keep the original one-packet helper.
    v1 = panel.split("if (layout_v2) {", 1)[1].split("return;", 1)[1]
    assert "flow_vertical(8, 3, 9, 6" in v1
    assert "flow_horizontal(3, 8, 6, 9" in v1


def test_alpha928_versions_coordinate_core_and_panel2() -> None:
    """A firmware-behaviour change advances both core and panel identities."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    panel = PANEL.read_text(encoding="utf-8")
    panel_health = PANEL_HEALTH.read_text(encoding="utf-8")
    reason = str(bundle["maintenance"]["reason"]).lower()

    assert manifest["version"] == "0.9.0-alpha9.31"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.3"
    assert 'panel_config_version: "0.9.0-alpha9-panel.3"' in panel
    assert 'PANEL_CONFIG_VERSION = "0.9.0-alpha9-panel.3"' in panel_health
    assert "stagger" in reason
    assert "v2" in reason
    assert "v1" in reason
    assert "no optimiser" in reason
