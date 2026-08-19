"""Regression coverage for Alpha7.31 solar-aware inverter headroom."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha731_solar_headroom.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "agile-solar-aware-inverter-headroom.md"


def test_alpha731_baseline_is_retained_in_later_alpha7_releases() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    version = str(manifest["version"])
    assert version.startswith("0.7.0-alpha7.")
    assert int(version.rsplit(".", 1)[1]) >= 31


def test_alpha731_module_parses() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha731_installs_after_alpha730() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha731_solar_headroom_patch" in loader
    assert loader.rindex("install_alpha731_solar_headroom_patch()") > loader.rindex(
        "install_alpha730_current_routing_patch()"
    )


def test_alpha731_patches_shared_dispatch_target_before_shadow() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "dispatch = alpha717._dispatch_targets" in source
    assert (
        "alpha717._dispatch_targets = _dispatch_targets_with_solar_headroom" in source
    )
    assert (
        "inverter_headroom = max(config.inverter_limit_kw - routed_solar_ac, 0.0)"
        in source
    )
    assert "battery_headroom = min(" in source
    assert '"battery_export_target_kw": round(permitted_export, 3)' in source
    assert '"battery_discharge_target_kw": round(permitted_total, 3)' in source


def test_alpha731_routes_solar_to_ac_first_while_discharging() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"basis": "Feed-in First solar AC before battery discharge"' in source
    assert '"solar_to_battery_kw_while_discharging": 0.0' in source
    assert '"solar_to_battery_kw": 0.0' in source
    assert "solar_export = max(routed_solar_ac - solar_to_home, 0.0)" in source
    assert "grid_export = solar_export + battery_export" in source


def test_alpha731_doc_exists() -> None:
    assert DOC.exists()
    text = DOC.read_text(encoding="utf-8")
    assert "7 kW" in text
    assert "solar" in text.lower()
