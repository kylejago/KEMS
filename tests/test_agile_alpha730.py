"""Regression coverage for Alpha7.30 Agile current-routing snapshot parity."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha730_current_routing.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "agile-current-routing-snapshot-parity.md"


def test_alpha730_patch_remains_packaged() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert any(
        marker in manifest
        for marker in ('"version": "0.8.0-alpha8.', '"version": "0.9.0-alpha9.')
    )
    assert PATCH.exists()


def test_alpha730_module_parses() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha730_installs_after_alpha729() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha730_current_routing_patch" in loader
    assert loader.rindex("install_alpha730_current_routing_patch()") > loader.rindex(
        "install_alpha729_live_routing_parity_patch()"
    )


def test_alpha730_rebuilds_current_proposal_simulation_each_scan() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "SimulationEngine().simulate_today(" in source
    assert 'getattr(self, "_panel_today_records", [])' in source
    assert 'getattr(self, "_rolling_now", None)' in source
    assert 'getattr(self, "_rolling_config", None)' in source


def test_alpha730_uses_current_settlement_slot_not_previous_complete_slot() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "if start <= now_utc < end:" in source
    assert '"routing_slot": slot.get("label")' in source
    assert '"routing_valid_from"' in source
    assert '"routing_valid_to"' in source


def test_alpha730_substitutes_exact_rolling_battery_candidate() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'plan.get("current_house_battery_kw")' in source
    assert 'plan.get("current_battery_export_target_kw")' in source
    assert 'plan.get("current_battery_discharge_target_kw")' in source
    assert '"battery_candidate_basis": "exact current Agile rolling target"' in source


def test_alpha730_keeps_solar_export_in_grid_export_total() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "grid_export = base_solar_export + candidate_export" in source
    assert '"solar_export_kw": round(max(base_solar_export, 0.0), 3)' in source
    assert '"grid_export_kw": round(max(grid_export, 0.0), 3)' in source


def test_alpha730_replaces_stale_decision_and_routing_basis() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'plan.get("dispatch_action")' in source
    assert '"routing_basis": "current coordinator routing snapshot"' in source
    assert '"current_action": snapshot.get("routing_action")' in source


def test_alpha730_preserves_elapsed_slot_values_only_as_evidence() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'attrs["elapsed_slot_average_evidence"]' in source
    assert '"simulated_house_load_basis": "current coordinator digital twin"' in source
    assert "Digital-twin house demand" in source
    assert "Digital-twin slot-average demand" not in source


def test_alpha730_replaces_entire_current_routing_card() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "| Flow | Current power |" in source
    assert "one current KEMS coordinator routing snapshot" in source
    assert (
        "**Current decision:** {{ state_attr(e, 'routing_action') or '—' }}" in source
    )
    assert "_patch_current_routing_card" in source


def test_alpha730_is_reporting_only_and_keeps_hardware_blocked() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"reporting_only": True' in source
    assert '"hardware_writes": "blocked"' in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "validate_shadow_command(" not in source
    assert "build_agile_shadow_command(" not in source
    assert "_rolling_plan(" not in source


def test_alpha730_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.30" in source
    assert "current coordinator routing snapshot" in source
    assert "Alpha7.28" in source
    assert "13-point" in source
    assert "Real FoxESS hardware writes remain blocked" in source
