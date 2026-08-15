"""Regression tests for commissioning readiness and panel health."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
COMMISSIONING = ROOT / "custom_components" / "kems" / "commissioning.py"
PANEL = ROOT / "custom_components" / "kems" / "panel.py"
DIAGNOSTICS = ROOT / "custom_components" / "kems" / "diagnostics.py"
SENSOR = ROOT / "custom_components" / "kems" / "sensor.py"
DASHBOARD = ROOT / "dashboards" / "kems_master_dashboard.yaml"


def test_commissioning_is_read_only_and_shadow_limited() -> None:
    """The readiness layer must not unlock real inverter writes."""
    content = COMMISSIONING.read_text(encoding="utf-8")
    assert '"maximum_allowed_stage": "shadow"' in content
    assert '"ready_for_control": False' in content
    assert '"real_hardware_writes": "blocked"' in content
    assert "commands_permitted" in content
    assert "Real inverter writes remain hard-blocked" in content


def test_commissioning_checks_foxess_sources_directions_and_limits() -> None:
    """Commissioning should gate on the physical KH7 data contract."""
    content = COMMISSIONING.read_text(encoding="utf-8")
    for token in (
        'FOXESS_PLATFORM = "foxess_modbus"',
        '"battery_power_direction"',
        '"grid_direction"',
        '"kh7_limits"',
        '"eps_limit"',
        '"site_import_limit"',
        '"shadow_planner"',
        '"emergency_stop"',
    ):
        assert token in content


def test_commissioning_entities_and_dashboard_are_registered() -> None:
    """Home Assistant should expose one clear commissioning operating view."""
    sensor = SENSOR.read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")
    assert "build_commissioning_entities" in sensor
    assert "sensor.kems_commissioning_readiness" in dashboard
    assert "sensor.kems_panel_management_status" in dashboard
    assert "sensor.kems_panel_firmware_version" in dashboard
    assert "path: commissioning" in dashboard
    assert "Shadow command" in dashboard


def test_panel_health_is_persistent_and_diagnostic_visible() -> None:
    """OTA proof should survive a later Home Assistant restart and diagnostics."""
    panel = PANEL.read_text(encoding="utf-8")
    diagnostics = DIAGNOSTICS.read_text(encoding="utf-8")
    assert 'PANEL_HEALTH_STORAGE_KEY = "kems.panel_health"' in panel
    assert "Store(" in panel
    assert "last_ota_attempt" in panel
    assert "last_ota_success" in panel
    assert "esphome_job_id" in panel
    assert '"commissioning": build_commissioning_snapshot' in diagnostics
    assert '"panel_health": panel_health_snapshot' in diagnostics
