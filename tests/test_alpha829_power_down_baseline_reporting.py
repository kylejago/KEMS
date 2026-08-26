"""Regression coverage for Alpha8.29 Power Down baseline reporting."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_power_down_baseline_entity_explains_source_truth() -> None:
    """Missing export baseline is explicitly reported as not required."""
    source = (ROOT / "custom_components" / "kems" / "binary_sensor.py").read_text()

    assert 'name="Power Down source baseline incomplete"' in source
    assert '"export_baseline_required": False' in source
    assert "Octopus source marks calculation" in source
    assert "export baseline not required" in source
    assert "grid export makes net " in source
    assert "import negative" in source


def test_missing_export_baseline_does_not_change_reward_equation() -> None:
    """Reward remains baseline import minus actual net import/export."""
    simulation = (
        ROOT / "custom_components" / "kems" / "kems_core" / "simulation.py"
    ).read_text()
    accounting = (ROOT / "custom_components" / "kems" / "power_down.py").read_text()

    assert "return max(imported, 0.0), \"import_only_assumed_zero_export\"" in simulation
    assert "simulated_net = simulated_import_kwh - simulated_export_kwh" in simulation
    assert "reduction = max(baseline_interval - simulated_net, 0.0)" in simulation
    assert "float(imported) - float(exported or 0.0)" in accounting


def test_alpha829_version_and_release_scope() -> None:
    """Alpha8.29 changes KEMS core reporting only."""
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())

    assert manifest["version"] == "0.8.0-alpha8.29"
    assert bundle["maintenance"]["affected_components"] == ["kems_core"]
    assert "export baseline is not required" in bundle["maintenance"]["reason"]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
