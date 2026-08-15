"""Regression tests for the coordinated KEMS update contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
ORCHESTRATOR = ROOT / "custom_components" / "kems" / "update_orchestrator.py"
INIT = ROOT / "custom_components" / "kems" / "__init__.py"
SENSOR = ROOT / "custom_components" / "kems" / "sensor.py"
SWITCH = ROOT / "custom_components" / "kems" / "switch.py"
SELECT = ROOT / "custom_components" / "kems" / "select.py"
DASHBOARD = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"
PACKAGED_DASHBOARD = ROOT / "dashboards" / "kems_master_dashboard.yaml"


def test_update_orchestrator_is_opt_in_and_uses_a_maintenance_window() -> None:
    """Unattended updates must be explicit and disruptive work must be windowed."""
    content = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "automatic_updates: bool = False" in content
    assert 'maintenance_start: str = "03:00"' in content
    assert 'maintenance_end: str = "04:00"' in content
    assert "automatic_restart: bool = True" in content
    assert "backup_before_update: bool = True" in content
    assert "_inside_window" in content
    assert "_next_window_start" in content


def test_opted_out_release_is_available_not_falsely_scheduled() -> None:
    """Discovery must not imply unattended maintenance before the user opts in."""
    content = ORCHESTRATOR.read_text(encoding="utf-8")
    assert '"available"\n                if not automatic' in content
    assert 'notice_status = "scheduled" if automatic' in content
    assert 'return "Update available"' in content
    assert "Automatic updates are disabled" in content


def test_update_orchestrator_installs_exact_kems_target_and_restarts_ha() -> None:
    """KEMS must converge on the bundle target rather than blindly install latest."""
    content = ORCHESTRATOR.read_text(encoding="utf-8")
    assert '"update",\n                    "install"' in content
    assert '"version": target' in content
    assert '"homeassistant",\n            "restart"' in content
    assert "installed_waiting_restart" in content
    assert "async_verify_pending" in content


def test_release_bundle_is_checksum_verified_and_public_site_is_reserved() -> None:
    """Coordinated releases require a verified manifest and know every target role."""
    content = ORCHESTRATOR.read_text(encoding="utf-8")
    assert 'BUNDLE_ASSET = "kems-bundle.json"' in content
    assert 'BUNDLE_CHECKSUM_ASSET = f"{BUNDLE_ASSET}.sha256"' in content
    assert "hashlib.sha256(manifest_bytes).hexdigest()" in content
    assert (
        'for key in ("property_web", "pi_agent", "pi_system", "public_web")' in content
    )
    assert '"delegated" if target is not None else "not-targeted"' in content


def test_home_assistant_update_entity_is_a_bootstrap_fallback() -> None:
    """Automatic KEMS-only releases still work before every release has a bundle."""
    content = ORCHESTRATOR.read_text(encoding="utf-8")
    assert 'self.hass.states.get("update.kems_update")' in content
    assert "_standalone_bundle_from_update_entity" in content
    assert '"delivery": "home-assistant-update"' in content


def test_update_entities_are_wired_into_home_assistant() -> None:
    """The policy/status controls should be normal KEMS entities."""
    init = INIT.read_text(encoding="utf-8")
    sensors = SENSOR.read_text(encoding="utf-8")
    switches = SWITCH.read_text(encoding="utf-8")
    selects = SELECT.read_text(encoding="utf-8")
    assert "Platform.TIME" in init
    assert "async_setup_update_orchestrator" in init
    assert "build_update_sensor_entities" in sensors
    assert "build_update_switch_entities" in switches
    assert "build_update_select_entities" in selects


def test_managed_dashboard_has_update_and_maintenance_view() -> None:
    """Users need one visible place to confirm that every component is current."""
    assert DASHBOARD.read_bytes() == PACKAGED_DASHBOARD.read_bytes()
    content = DASHBOARD.read_text(encoding="utf-8")
    assert "path: updates" in content
    assert "sensor.kems_update_status" in content
    assert "sensor.kems_maintenance_status" in content
    assert "switch.kems_automatic_updates" in content
    assert "time.kems_maintenance_window_start" in content
    assert "Component verification" in content
    assert "Recent update history" in content


def test_real_control_is_not_unlocked_by_update_orchestration() -> None:
    """Update plumbing must not weaken the commissioning write lock."""
    content = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "real_backend" not in content
    assert "commands_permitted" not in content
