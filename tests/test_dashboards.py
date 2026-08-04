"""Validation for the shipped KEMS dashboard collection."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
DASHBOARDS = ROOT / "dashboards"


def test_all_dashboard_yaml_is_valid() -> None:
    """Every shipped dashboard should parse as YAML."""
    files = sorted(DASHBOARDS.glob("*.yaml"))
    assert len(files) == 10
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


def test_diagnostic_dashboard_lists_current_kems_entities_dynamically() -> None:
    """Diagnostics must survive entity-ID suffixes and future KEMS additions."""
    text = (DASHBOARDS / "kems_diagnostics_all_entities.yaml").read_text(
        encoding="utf-8"
    )
    assert "states.sensor" in text
    assert "states.binary_sensor" in text
    assert "states.update" in text
    assert "startswith('sensor.kems_')" in text
    assert "startswith('binary_sensor.kems_')" in text
    assert "startswith('update.kems_')" in text


def test_actual_vs_simulated_dashboard_includes_paced_export_diagnostics() -> None:
    """The simple comparison view must expose the new KH7 pacing plan."""
    text = (DASHBOARDS / "kems_actual_vs_simulated.yaml").read_text(encoding="utf-8")
    assert "panel: true" in text
    assert "sensor.kems_learning_confidence" in text
    assert "sensor.kems_simulated_battery_to_home_power" in text
    assert "sensor.kems_simulated_battery_export_power" in text
    assert "sensor.kems_target_battery_export_power" in text
    assert "sensor.kems_exportable_battery_energy_remaining" in text
    assert "sensor.kems_projected_soc_at_cheap_period_start" in text
    assert "sensor.kems_home_reserve_forecast_source" in text
    assert "sensor.kems_projected_grid_import_before_cheap_period" in text
    assert "binary_sensor.kems_battery_export_paused_for_home_reserve" in text


def test_dashboards_include_power_down_planning() -> None:
    """Dashboards must use Home Assistant's Power Down entity IDs."""
    for name in (
        "kems_actual_vs_simulated.yaml",
        "kems_diagnostics_all_entities.yaml",
    ):
        text = (DASHBOARDS / name).read_text(encoding="utf-8")
        assert "binary_sensor.kems_power_down_session_joined" in text
        assert "sensor.kems_power_down_session_battery_reserve" in text
        assert "sensor.kems_estimated_power_down_session_bonus" in text
        assert "sensor.kems_estimated_power_down_session_total_income" in text
        assert (
            "binary_sensor.kems_battery_export_reduced_for_power_down_session" in text
        )
        assert "sensor.kems_saving_session" not in text
        assert "binary_sensor.kems_saving_session" not in text
        assert "for_saving_session" not in text


def test_control_lab_dashboard_exposes_island_and_write_boundary() -> None:
    """The control lab must show desired commands and the hard write block."""
    text = (DASHBOARDS / "kems_control_lab.yaml").read_text(encoding="utf-8")
    assert "select.kems_operating_mode" in text
    assert "select.kems_virtual_scenario" in text
    assert "switch.kems_emergency_stop" in text
    assert "binary_sensor.kems_whole_house_island_mode" in text
    assert "sensor.kems_island_solar_to_battery_power" in text
    assert "binary_sensor.kems_control_commands_permitted" in text
    assert "cannot send real FoxESS commands" in text
