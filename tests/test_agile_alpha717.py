"""Regression coverage for alpha7.17 Agile deadline saturation."""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def _string_constant(path: Path, name: str) -> str:
    """Read one literal module constant without importing Home Assistant."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, str)
            return value
    raise AssertionError(f"{name} was not found in {path}")


def test_unreachable_deadline_uses_target_floor_and_maximum_discharge() -> None:
    """Unreachable mode must stop protecting extra forecast battery energy."""
    source = (INTEGRATION / "agile_alpha717_dispatch.py").read_text(
        encoding="utf-8"
    )
    assert 'mode = "maximum_discharge"' in source
    assert 'context.get("mode") == "maximum_discharge"' in source
    assert "target = capacity * _target_percent(config) / 100.0" in source
    assert 'total_target_kw = effective_kw' in source
    assert '"maximum discharge — 10% target physically unreachable; house first"' in source


def test_house_has_priority_over_battery_export_target() -> None:
    """Battery export must use only discharge headroom left after house demand."""
    source = (INTEGRATION / "agile_alpha717_dispatch.py").read_text(
        encoding="utf-8"
    )
    assert "total_target_kw - house_kw" in source
    assert "config.inverter_limit_kw - house_kw" in source
    assert "config.max_discharge_kw - house_kw" in source
    assert '"battery_export_target_kw"' in source


def test_rolling_plan_drives_current_slot_and_replans_unreachable_future() -> None:
    """The current scan must expose a dispatch target, not only future labels."""
    source = (INTEGRATION / "agile_alpha717_dispatch.py").read_text(
        encoding="utf-8"
    )
    assert 'slot["rolling_target_battery_export_kw"]' in source
    assert 'slot["rolling_target_total_discharge_kw"]' in source
    assert 'slot["rolling_planned_battery_export_kwh"]' in source
    assert 'state["current_action"] = targets.get("action")' in source
    assert 'future["actions"] = [' in source


def test_live_routing_uses_elapsed_slot_and_preserves_simulated_values() -> None:
    """Current power must not divide a partial slot by a full half-hour."""
    source = (INTEGRATION / "agile_alpha717_dispatch.py").read_text(
        encoding="utf-8"
    )
    assert "elapsed_hours = min(" in source
    assert '"current simulated half-hour — elapsed-slot average"' in source
    assert 'attrs["simulated_elapsed_battery_export_kw"]' in source
    assert 'attrs["current_battery_export_kw"] = round(target_export, 3)' in source
    assert 'attrs["routing_basis"] = "rolling target — current coordinator scan"' in source


def test_alpha717_runtime_install_order_is_after_rolling_and_live() -> None:
    """Alpha7.17 must wrap the already-installed rolling and live publishers."""
    source = (INTEGRATION / "agile_smart_export_runtime.py").read_text(
        encoding="utf-8"
    )
    assert source.index("install_rolling_replan_patch()") < source.index(
        "install_alpha717_dispatch_patch()"
    )
    assert source.index("install_live_scenario_patch()") < source.index(
        "install_alpha717_dispatch_patch()"
    )
    assert source.index("install_alpha716_dashboard_patch()") < source.index(
        "install_alpha717_dashboard_patch()"
    )


def test_alpha717_dashboard_patch_keeps_valid_yaml_fragments() -> None:
    """The extra rolling entities must remain valid Lovelace YAML."""
    path = INTEGRATION / "agile_alpha717_dashboard.py"
    replacement = _string_constant(path, "_ROLLING_REPLACEMENT")
    sample = (
        "type: entities\n"
        "title: Rolling Agile battery export plan\n"
        "entities:\n"
        f"{replacement}"
    )
    parsed = yaml.safe_load(sample)
    entities = parsed["entities"]
    assert any(
        item.get("entity") == "sensor.kems_agile_dispatch_mode" for item in entities
    )
    assert any(
        item.get("entity") == "sensor.kems_agile_battery_export_target_now"
        for item in entities
    )
