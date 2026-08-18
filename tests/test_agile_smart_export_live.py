"""Regression coverage for the Agile Smart Export live scenario view."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
LIVE = ROOT / "custom_components" / "kems" / "agile_smart_export_live.py"
RUNTIME = ROOT / "custom_components" / "kems" / "agile_smart_export_runtime.py"


def test_runtime_installs_agile_live_scenario_patch() -> None:
    """The efficient runtime must load the live-scenario reporting layer."""
    content = RUNTIME.read_text(encoding="utf-8")
    assert "from .agile_smart_export_live import install_live_scenario_patch" in content
    assert "install_live_scenario_patch()" in content


def test_agile_live_dashboard_view_is_managed() -> None:
    """The master dashboard must gain a dedicated Agile Smart Export tab."""
    content = LIVE.read_text(encoding="utf-8")
    assert "title: Agile Smart Export" in content
    assert "path: agile-smart-export" in content
    assert "Agile Smart Export — Live Scenario" in content
    assert "Current Agile Smart Export power routing" in content
    assert "Current and upcoming Agile plan" in content


def test_agile_live_view_distinguishes_hardware_and_simulated_soc() -> None:
    """Hardware SOC and the shadow-strategy SOC must never be conflated."""
    content = LIVE.read_text(encoding="utf-8")
    assert 'sensor.kems_agile_simulated_battery_soc_now' in content
    assert "Live hardware battery SOC" in content
    assert "Agile simulated SOC now" in content
    assert 'today.get("agile_smart_export")' in content
    assert 'agile.get("ending_soc_percent")' in content


def test_unsettled_current_slot_falls_back_without_inventing_power() -> None:
    """Routing may use the latest complete slot but must label that basis."""
    content = LIVE.read_text(encoding="utf-8")
    assert 'return slot, "current simulated half-hour"' in content
    assert 'return latest[1], "latest completed simulated half-hour"' in content
    assert "complete = all(" in content
    assert "The live decision and Agile rate are current." in content
