"""Validation for the shipped KEMS dashboard collection."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
DASHBOARDS = ROOT / "dashboards"


def test_all_dashboard_yaml_is_valid() -> None:
    """Every shipped dashboard should parse as YAML."""
    files = sorted(DASHBOARDS.glob("*.yaml"))
    assert len(files) == 5
    for path in files:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(content, dict)
        assert content.get("views")


def test_comparison_dashboards_include_live_and_simulated_flows() -> None:
    """The main dashboards should compare both systems explicitly."""
    for name in (
        "kems_live_vs_simulated_advanced.yaml",
        "kems_live_vs_simulated_builtin.yaml",
    ):
        text = (DASHBOARDS / name).read_text(encoding="utf-8")
        assert "sensor.kems_grid_net_power" in text
        assert "sensor.kems_simulated_grid_net_power" in text
        assert "sensor.kems_observed_grid_export_today" in text
        assert "sensor.kems_simulated_grid_export_today" in text


def test_whole_home_dashboards_include_gas() -> None:
    """Whole-home views must contain gas and combined cost entities."""
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in DASHBOARDS.glob("*.yaml")
    )
    assert "sensor.kems_gas_usage_today" in text
    assert "sensor.kems_whole_home_observed_cost_today" in text
    assert "sensor.kems_whole_home_simulated_cost_today" in text
