"""Regression coverage for the packaged KEMS panel.1 authority and EV policy."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGED = ROOT / "custom_components" / "kems" / "kems16x16.yaml"
COMPAT = ROOT / "custom_components" / "kems" / "agile_alpha7_compat.py"
RENDER = ROOT / "scripts" / "render_managed_panel.py"


def _packaged() -> str:
    return PACKAGED.read_text(encoding="utf-8")


def test_packaged_panel_reports_panel1_and_reads_ev_policy() -> None:
    content = _packaged()
    assert 'panel_config_version: "0.8.0-alpha8-panel.1"' in content
    assert "ev_allowed: binary_sensor.kems_ev_charging_allowed_by_control" in content
    assert "id: ha_ev_allowed" in content
    assert "entity_id: ${ev_allowed}" in content


def test_full_kems_agile_ev_blocked_is_red_without_charge_animation() -> None:
    content = _packaged()
    assert "const bool agile_ev_mode = selected_scenario == 7;" in content
    assert "const bool ev_blocked_by_kems =" in content
    assert "agile_ev_mode && ev_connected && !ev_allowed_by_kems" in content
    assert "if (ev_blocked_by_kems)" in content
    assert "rect(7, 15, 10, 16, RED);" in content
    assert "else if (ev_charging_for_display)" in content
    assert "pulse(MAGENTA)" in content


def test_live_panel_keeps_actual_ev_semantics() -> None:
    content = _packaged()
    assert "ev_charging && (!agile_ev_mode || ev_allowed_by_kems)" in content
    assert "else if (ev_connected)" in content
    assert "rect(7, 15, 10, 16, MAGENTA);" in content


def test_panel1_no_longer_uses_runtime_transform() -> None:
    compat = COMPAT.read_text(encoding="utf-8")
    renderer = RENDER.read_text(encoding="utf-8")
    assert "panel_ev_policy" not in compat
    assert "apply_ev_policy_panel" not in renderer
    assert "SOURCE.read_bytes()" in renderer
    assert "OUTPUT.write_bytes" in renderer
    assert not (ROOT / "custom_components" / "kems" / "panel_ev_policy.py").exists()
