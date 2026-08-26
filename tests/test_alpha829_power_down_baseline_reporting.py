"""Regression coverage for Alpha8.29 Power Down baseline reporting."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_power_down_baseline_entity_preserves_octopus_source_truth() -> None:
    """The source-incomplete flag must still mean Octopus reported partial data."""
    source = (ROOT / "custom_components" / "kems" / "binary_sensor.py").read_text()

    assert 'name="Power Down source baseline incomplete"' in source
    assert "Octopus source marks calculation" in source
    assert '"octopus_source_calculation_incomplete"' in source


def test_power_down_reward_equation_remains_net_meter_based() -> None:
    """Reward remains historical net baseline minus actual net import/export."""
    simulation = (
        ROOT / "custom_components" / "kems" / "kems_core" / "simulation.py"
    ).read_text()
    accounting = (ROOT / "custom_components" / "kems" / "power_down.py").read_text()

    assert "simulated_net = simulated_import_kwh - simulated_export_kwh" in simulation
    assert "reduction = max(baseline_interval - simulated_net, 0.0)" in simulation
    assert "float(imported) - float(exported or 0.0)" in accounting


def test_alpha829_release_contract_is_successor_safe() -> None:
    """Later Alpha8 releases retain the coordinated core/dashboard boundary."""
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())

    prefix = "0.8.0-alpha8."
    assert manifest["version"].startswith(prefix)
    assert int(manifest["version"].removeprefix(prefix)) >= 29
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
