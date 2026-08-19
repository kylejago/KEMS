"""Regression coverage for alpha7.23 Agile shadow-command parity."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha723_shadow.py"
LOADER = KEMS / "agile_smart_export_runtime.py"


def test_alpha723_shadow_patch_remains_installed() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha723_shadow_patch" in loader
    assert "install_alpha723_shadow_patch()" in loader


def test_alpha723_shadow_module_parses() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha723_uses_existing_independent_shadow_validator() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "validate_shadow_command(candidate, config)" in source
    assert "shadow_plan_vs_outcome(candidate, simulation)" in source
    assert "same 13-point independent shadow safety envelope" in source


def test_alpha723_preserves_exact_optimizer_targets_without_clipping() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'plan.get("current_battery_export_target_kw")' in source
    assert 'plan.get("current_battery_discharge_target_kw")' in source
    assert 'plan.get("current_house_battery_kw")' in source
    assert "desired_battery_export_power_kw=round(export, 3)" in source
    assert "desired_total_discharge_power_kw=round(discharge, 3)" in source
    assert '"export_target_matches_optimizer"' in source
    assert '"discharge_target_matches_optimizer"' in source
    assert '"house_target_matches_optimizer"' in source


def test_alpha723_horizon_hold_requires_zero_shadow_export() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'plan.get("price_horizon_battery_export_held")' in source
    assert '"horizon_hold_forces_zero_export"' in source
    assert "candidate.desired_battery_export_power_kw <= 0.001" in source
    assert 'status = "PASS — price-horizon hold"' in source


def test_alpha723_keeps_deadline_override_visible() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'plan.get("price_horizon_deadline_override")' in source
    assert 'status = "PASS — deadline override"' in source


def test_alpha723_unsafe_target_is_blocked_not_silently_corrected() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'status = "BLOCKED — shadow safety validation"' in source
    assert "The optimiser target is not clipped here" in source
    assert '"safe_to_write_hardware": False' in source


def test_alpha723_has_no_hardware_service_write_path() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".async_call(" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "commands_permitted=False" in source
    assert '"hardware_writes": "blocked"' in source
    assert '"real_backend_available": False' in source


def test_alpha723_publishes_shadow_targets_and_evidence() -> None:
    source = PATCH.read_text(encoding="utf-8")
    for entity_id in (
        "sensor.kems_agile_shadow_status",
        "sensor.kems_agile_shadow_command",
        "sensor.kems_agile_shadow_safety",
        "sensor.kems_agile_shadow_target_export",
        "sensor.kems_agile_shadow_target_total_discharge",
    ):
        assert entity_id in source
    assert 'self._state["agile_shadow"]' in source
    assert '"agile_decisions"' in source


def test_alpha723_installs_after_price_horizon_safety() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha723_shadow_patch" in loader
    assert loader.rindex("install_alpha723_shadow_patch()") > loader.rindex(
        "install_alpha722_price_horizon_patch()"
    )
