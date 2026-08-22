"""Regression contract for the FoxESS telemetry commissioning gate."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
COMMISSIONING = ROOT / "custom_components" / "kems" / "commissioning.py"


def test_commissioning_requires_stable_foxess_telemetry_for_shadow_readiness() -> None:
    """Ready for Shadow must include sustained physical telemetry evidence."""
    content = COMMISSIONING.read_text(encoding="utf-8")

    for token in (
        "assess_foxess_telemetry_stability",
        '"foxess_telemetry_stability"',
        '"foxess_telemetry_mapping_gate_passed"',
        "coordinator.settings.scan_interval_seconds",
        '"battery_power_mapping"',
        '"FoxESS telemetry stability"',
    ):
        assert token in content

    assert content.index("foxess_physical_mappings_ready = all(") < content.index(
        "assess_foxess_telemetry_stability("
    )
    assert content.index("checks.append(telemetry_check)") < content.index(
        'required = [item for item in checks if item["required"]]'
    )


def test_telemetry_gate_cannot_unlock_real_control() -> None:
    """Commissioning telemetry evidence must remain shadow-only."""
    content = COMMISSIONING.read_text(encoding="utf-8")

    assert '"ready_for_control": False' in content
    assert '"maximum_allowed_stage": "shadow"' in content
    assert '"real_hardware_writes": "blocked"' in content
    assert "commands_permitted = True" not in content
    assert "safe_to_write_hardware = True" not in content
    assert ".services.async_call(" not in content
