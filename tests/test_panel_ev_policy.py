"""Regression coverage for EV policy projection onto the managed panel."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "custom_components" / "kems" / "panel_ev_policy.py"
PACKAGED = ROOT / "custom_components" / "kems" / "kems16x16.yaml"
SPEC = importlib.util.spec_from_file_location("kems_panel_ev_policy", MODULE)
assert SPEC is not None and SPEC.loader is not None
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


def _rendered() -> str:
    return policy.apply_ev_policy_panel(PACKAGED.read_text(encoding="utf-8"))


def test_runtime_panel_reports_panel1_and_reads_ev_policy() -> None:
    content = _rendered()
    assert 'panel_config_version: "0.8.0-alpha8-panel.1"' in content
    assert "ev_allowed: binary_sensor.kems_ev_charging_allowed_by_control" in content
    assert "id: ha_ev_allowed" in content
    assert "entity_id: ${ev_allowed}" in content


def test_full_kems_agile_ev_blocked_is_red_without_charge_animation() -> None:
    content = _rendered()
    assert "const bool agile_ev_mode = selected_scenario == 7;" in content
    assert "const bool ev_blocked_by_kems =" in content
    assert "agile_ev_mode && ev_connected && !ev_allowed_by_kems" in content
    assert "if (ev_blocked_by_kems)" in content
    assert "rect(7, 15, 10, 16, RED);" in content
    assert "else if (ev_charging_for_display)" in content
    assert "pulse(MAGENTA)" in content


def test_live_panel_keeps_actual_ev_semantics() -> None:
    content = _rendered()
    assert "ev_charging && (!agile_ev_mode || ev_allowed_by_kems)" in content
    assert "else if (ev_connected)" in content
    assert "rect(7, 15, 10, 16, MAGENTA);" in content


def test_panel_transform_is_idempotent() -> None:
    once = _rendered()
    assert policy.apply_ev_policy_panel(once) == once
