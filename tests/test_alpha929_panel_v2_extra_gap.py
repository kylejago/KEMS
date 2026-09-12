"""Regression contracts for Alpha9.29 V2 panel extra packet gap."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "custom_components" / "kems" / "kems16x16.yaml"
PANEL_HEALTH = ROOT / "custom_components" / "kems" / "panel.py"
MANIFEST = ROOT / "custom_components" / "kems" / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"


def test_alpha929_v2_keeps_one_dark_row_between_flow_packets() -> None:
    """V2 five-row links use four-position spacing; V1 timing is untouched."""
    panel = PANEL.read_text(encoding="utf-8")

    assert "auto flow_vertical_v2_dual" in panel
    assert "auto flow_vertical_v2" in panel
    assert "const int launch_spacing = 4;" in panel
    assert "one dark row between packets" in panel

    v2 = panel.split("if (layout_v2) {", 1)[1].split("return;", 1)[0]
    assert "flow_vertical_v2(4, 3, 5, 7" in v2
    assert "flow_vertical_v2(8, 3, 9, 7" in v2
    assert "flow_vertical_v2(12, 3, 13, 7" in v2
    assert "flow_vertical_v2(5, 10, 6, 14" in v2
    assert "flow_vertical_v2(11, 10, 12, 14" in v2
    assert "flow_vertical_v2_dual(" in v2

    # V1 keeps the established one-packet helpers and 2x4 geometry.
    v1 = panel.split("if (layout_v2) {", 1)[1].split("return;", 1)[1]
    assert "flow_vertical(8, 3, 9, 6" in v1
    assert "flow_horizontal(3, 8, 6, 9" in v1


def test_alpha929_versions_coordinate_core_and_panel3() -> None:
    """A firmware-behaviour change advances both core and panel identities."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    panel = PANEL.read_text(encoding="utf-8")
    panel_health = PANEL_HEALTH.read_text(encoding="utf-8")
    reason = str(bundle["maintenance"]["reason"]).lower()

    assert manifest["version"] == "0.9.0-alpha9.30"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.3"
    assert 'panel_config_version: "0.9.0-alpha9-panel.3"' in panel
    assert 'PANEL_CONFIG_VERSION = "0.9.0-alpha9-panel.3"' in panel_health
    assert "extra gap" in reason
    assert "v2" in reason
    assert "v1" in reason
    assert "no optimiser" in reason
