"""Regression contract for the FoxESS telemetry commissioning gate."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
COMMISSIONING = ROOT / "custom_components" / "kems" / "commissioning.py"
BACKEND = ROOT / "custom_components" / "kems" / "foxess_control_backend.py"


def test_commissioning_requires_stable_foxess_telemetry_for_shadow_readiness() -> None:
    """Ready for Shadow must include sustained physical telemetry evidence."""
    content = COMMISSIONING.read_text(encoding="utf-8")

    for token in (
        "assess_foxess_telemetry_stability",
        '"foxess_telemetry_stability"',
        '"foxess_telemetry_mapping_gate_passed"',
        '"foxess_site_mapping_gate_passed"',
        "commissioning_physical_mappings_ready",
        "coordinator.settings.scan_interval_seconds",
        '"battery_power_mapping"',
        '"FoxESS telemetry stability"',
    ):
        assert token in content

    assert content.index("commissioning_physical_mappings_ready = (") < content.index(
        "assess_foxess_telemetry_stability("
    )
    assert content.index("checks.append(telemetry_check)") < content.index(
        'required = [item for item in checks if item["required"]]'
    )


def test_telemetry_gate_alone_cannot_unlock_real_control() -> None:
    """Telemetry is necessary; independent runtime opt-ins still own writes."""
    content = COMMISSIONING.read_text(encoding="utf-8")
    backend = BACKEND.read_text(encoding="utf-8")

    assert '"ready_for_control": ready_for_control' in content
    assert 'state == "Ready for Shadow"' in content
    assert "and command_surface_ready" in content
    assert "and not solar_only_commissioning" in content
    assert "commands_permitted = True" not in content
    assert "safe_to_write_hardware = True" not in content
    assert 'control.operating_mode != "control"' in (
        ROOT / "custom_components" / "kems" / "kems_core" / "control_write_authority.py"
    ).read_text(encoding="utf-8")
    assert 'master_control_enabled=bool(coordinator.settings.control.control_enabled)' in backend
    assert 'user_commissioned=bool(coordinator.settings.control.commissioned)' in backend
