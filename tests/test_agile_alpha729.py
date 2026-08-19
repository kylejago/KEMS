"""Regression coverage for Alpha7.29 Agile live-routing parity."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha729_live_routing.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "agile-live-routing-parity.md"


def test_alpha729_manifest_is_alpha729_or_newer() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert '"version": "0.7.0-alpha7.' in manifest
    version = manifest.split('"version": "0.7.0-alpha7.', 1)[1].split('"', 1)[0]
    assert int(version) >= 29


def test_alpha729_module_parses() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha729_installs_after_alpha728() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha729_live_routing_parity_patch" in loader
    assert loader.rindex(
        "install_alpha729_live_routing_parity_patch()"
    ) > loader.rindex("install_alpha728_bounded_partial_horizon_patch()")


def test_alpha729_uses_same_live_house_entity_as_live_tab() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '_HOUSE_SENSOR = "sensor.kems_house_load"' in source
    assert 'attrs["current_house_load_kw"] = round(live_house_kw, 3)' in source
    assert 'attrs["live_house_load_source"] = _HOUSE_SENSOR' in source
    assert '"live KEMS house load"' in source


def test_alpha729_retains_simulated_house_demand_as_evidence() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'attrs["simulated_house_load_kw"] = simulated_house_kw' in source
    assert 'attrs["simulated_house_load_basis"] = simulated_basis' in source
    assert '"house_load_difference_kw"' in source
    assert '"simulated_house_load_kw": simulated_house_kw' in source
    assert '"reporting_only": True' in source


def test_alpha729_dashboard_labels_live_and_simulated_values_separately() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "House demand (live)" in source
    assert "states('sensor.kems_house_load')" in source
    assert "Digital-twin slot-average demand" in source
    assert "**House-demand basis:**" in source
    assert "| Flow | Power |" in source


def test_alpha729_is_reporting_only() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "_dispatch_targets(" not in source
    assert "rolling_export_plan" not in source
    assert "battery_export_target_kw" not in source
    assert "safe_to_write_hardware" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source


def test_alpha729_keeps_live_fallback_explicit() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"house_load_parity_available"' in source
    assert '"simulated elapsed-slot average fallback"' in source
    assert "if live_house_kw is not None:" in source


def test_alpha729_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.29" in source
    assert "sensor.kems_house_load" in source
    assert "Digital-twin slot-average demand" in source
    assert "reporting-only" in source
    assert "Alpha7.28" in source
