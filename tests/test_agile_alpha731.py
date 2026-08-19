"""Regression coverage for Alpha7.31 solar-aware inverter headroom."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha731_solar_headroom.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "agile-solar-aware-inverter-headroom.md"


def test_alpha731_manifest_is_exact() -> None:
    assert '"version": "0.7.0-alpha7.31"' in MANIFEST.read_text(encoding="utf-8")


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


def test_alpha731_shadow_and_replay_use_same_solar_ac_headroom() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "build_shadow = alpha723.build_agile_shadow_command" in source
    assert (
        "alpha723.build_agile_shadow_command = _build_shadow_with_solar_aware_ac"
        in source
    )
    assert "replay_base_ac = routed_solar_ac + base_discharge" in source
    assert "candidate_ac = routed_solar_ac + candidate_discharge" in source
    assert (
        '"basis": "solar_aware_feed_in_first_ac_substitute_candidate_discharge"'
        in source
    )
    assert '"total_kh7_ac_output_kw": round(replay_base_ac, 3)' in source


def test_alpha731_current_routing_snapshot_is_physically_coherent() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "current_snapshot = alpha730._snapshot" in source
    assert "alpha730._snapshot = _snapshot_with_solar_aware_routing" in source
    assert '"solar_to_battery_kw": 0.0' in source
    assert '"grid_to_battery_kw": 0.0' in source
    assert '"normalised_kh7_ac_output_kw": round(kh7_ac, 3)' in source
    assert '"solar_aware_discharge_routing": True' in source


def test_alpha731_preserves_zero_discharge_routing() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "if requested_total <= _EPSILON:" in source
    assert '"reason": "battery discharge is not active"' in source
    assert "if total_discharge <= _EPSILON:" in source
    assert 'snapshot["solar_aware_discharge_routing"] = False' in source


def test_alpha731_records_headroom_evidence_in_rolling_plan() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'plan["solar_aware_inverter_headroom"] = dict(evidence)' in source
    assert 'plan["solar_routed_ac_kw"]' in source
    assert 'plan["battery_inverter_headroom_kw"]' in source
    assert 'plan["solar_aware_requested_battery_export_kw"]' in source
    assert 'plan["solar_aware_permitted_battery_export_kw"]' in source


def test_alpha731_regression_example_matches_1600_proof() -> None:
    solar_kw = 2.631
    house_kw = 0.778
    inverter_limit_kw = 7.0
    battery_export_kw = inverter_limit_kw - solar_kw
    solar_export_kw = solar_kw - house_kw
    grid_export_kw = battery_export_kw + solar_export_kw

    assert round(battery_export_kw, 3) == 4.369
    assert round(solar_export_kw, 3) == 1.853
    assert round(grid_export_kw, 3) == 6.222
    assert round(solar_kw + battery_export_kw, 3) == 7.0


def test_alpha731_does_not_bypass_independent_safety_or_hardware_block() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "validate_shadow_command(" not in source


def test_alpha731_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.31" in source
    assert "4.369 kW" in source
    assert "6.222 kW" in source
    assert "13-point" in source
    assert "Real FoxESS hardware writes remain blocked" in source
