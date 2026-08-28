"""Alpha8.40 settled current-day control and presentation regressions."""

from pathlib import Path

from custom_components.kems.agile_current_day_presentation import (
    reconciled_current_day_simulation,
)
from custom_components.kems.kems_core import SimulationState


def _state() -> dict:
    return {
        "current_day_settlement_reconciliation": {
            "active": True,
            "applied": True,
            "all_accounting_checks_passed": True,
        },
        "periods": {
            "today": {
                "agile_smart_export": {
                    "ready": True,
                    "import_cost_pence": 159.13,
                    "export_income_pence": 127.56,
                    "grid_import_kwh": 45.552,
                    "grid_export_kwh": 8.338,
                    "solar_generation_kwh": 11.789,
                    "solar_to_home_kwh": 7.256,
                    "solar_to_battery_kwh": 4.307,
                    "solar_export_kwh": 0.0,
                    "grid_to_battery_kwh": 36.444,
                    "battery_to_home_kwh": 5.062,
                    "battery_export_kwh": 8.338,
                    "ending_soc_percent": 65.244,
                    "weighted_achieved_export_rate_pence": 15.2986,
                }
            }
        },
        "rolling_export_plan": {
            "available": True,
            "simulated_soc_percent": 65.2,
            "protected_house_energy_kwh": 5.219,
            "exportable_battery_energy_kwh": 26.851,
            "planned_battery_export_kwh": 26.851,
        },
    }


def _simulation() -> SimulationState:
    return SimulationState(
        ready=True,
        samples=142,
        actual_cost_pence=373.74,
        simulated_cost_pence=-32.73,
        saving_pence=406.47,
        simulated_import_cost_pence=159.13,
        simulated_export_income_pence=191.85,
        simulated_grid_import_kwh=45.552,
        simulated_grid_export_kwh=15.988,
        simulated_solar_generation_kwh=11.789,
        simulated_solar_to_home_kwh=0.0,
        simulated_solar_to_battery_kwh=4.307,
        simulated_solar_export_kwh=11.681,
        simulated_grid_to_battery_kwh=36.444,
        simulated_battery_charge_kwh=40.751,
        simulated_battery_to_home_kwh=12.317,
        simulated_battery_export_kwh=3.99,
        simulated_battery_soc=80.8,
        baseline_no_system_cost_pence=373.74,
        simulated_avoided_import_value_pence=214.61,
        simulated_system_value_pence=406.47,
        effective_export_rate_pence=12.0,
        exportable_battery_energy_kwh=33.566,
        reserved_for_home_kwh=5.219,
    )


def test_alpha840_headline_simulation_uses_settled_agile_accounting() -> None:
    """Headline sensors must use the same settled current-day Agile ledger."""
    result = reconciled_current_day_simulation(_simulation(), _state())

    assert result.simulated_cost_pence == 31.57
    assert result.saving_pence == 342.17
    assert result.simulated_import_cost_pence == 159.13
    assert result.simulated_export_income_pence == 127.56
    assert result.simulated_grid_import_kwh == 45.552
    assert result.simulated_grid_export_kwh == 8.338
    assert result.simulated_solar_generation_kwh == 11.789
    assert result.simulated_solar_to_home_kwh == 7.256
    assert result.simulated_solar_to_battery_kwh == 4.307
    assert result.simulated_solar_export_kwh == 0.0
    assert result.simulated_grid_to_battery_kwh == 36.444
    assert result.simulated_battery_charge_kwh == 40.751
    assert result.simulated_battery_to_home_kwh == 5.062
    assert result.simulated_battery_export_kwh == 8.338
    assert result.simulated_battery_soc == 65.2
    assert result.simulated_avoided_import_value_pence == 214.61
    assert result.simulated_system_value_pence == 342.17
    assert result.effective_export_rate_pence == 15.2986
    assert result.exportable_battery_energy_kwh == 26.851
    assert result.reserved_for_home_kwh == 5.219


def test_alpha840_unreconciled_state_leaves_generic_simulation_untouched() -> None:
    """A failed/incomplete settlement must never invent headline corrections."""
    state = _state()
    state["current_day_settlement_reconciliation"][
        "all_accounting_checks_passed"
    ] = False
    original = _simulation()

    assert reconciled_current_day_simulation(original, state) is original


def test_alpha840_coordinator_settles_before_control_and_rebuilds_after_shadow() -> (
    None
):
    """Control/shadow must see settled SOC and presentation must include new closes."""
    source = Path("custom_components/kems/coordinator.py").read_text()
    first_reconcile = source.index(
        "self._agile_smart_export.reconcile_current_day_settlements"
    )
    alignment = source.index("aligned_agile_control_views(simulation, agile_state)")
    shadow_update = source.index("await self._shadow_validation.async_update")
    second_reconcile = source.index(
        "self._agile_smart_export.reconcile_current_day_settlements",
        first_reconcile + 1,
    )
    final_presentation = source.index(
        "simulation = reconciled_current_day_simulation(",
        second_reconcile,
    )
    whole_home = source.index("whole_home = self._whole_home.summarise")

    assert first_reconcile < alignment < shadow_update < second_reconcile
    assert second_reconcile < final_presentation < whole_home


def test_alpha840_managed_dashboard_headlines_use_reconciled_sensor_surfaces() -> None:
    """Existing dashboard bindings inherit the reconciled backend authority."""
    dashboard = Path("custom_components/kems/kems_master_dashboard.yaml").read_text()
    sensor_source = Path("custom_components/kems/sensor.py").read_text()

    assert "sensor.kems_simulated_kems_cost_today" in dashboard
    assert "sensor.kems_simulated_saving_today" in dashboard
    assert "sensor.kems_whole_home_simulated_cost_today" in dashboard
    assert "sensor.kems_whole_home_simulated_saving_today" in dashboard
    assert 'key="simulated_saving_today"' in sensor_source
    assert "value_fn=lambda data: data.simulation.saving_pence" in sensor_source
    assert (
        "value_fn=lambda data: data.whole_home.simulated_total_cost_pence"
        in sensor_source
    )
    assert (
        "value_fn=lambda data: data.whole_home.simulated_saving_pence" in sensor_source
    )


def test_alpha840_no_hardware_write_or_version_named_patch_debt() -> None:
    """Alpha8.40 stays reporting/control-alignment only and adds no patch module."""
    module = Path(
        "custom_components/kems/agile_current_day_presentation.py"
    ).read_text()
    coordinator = Path("custom_components/kems/coordinator.py").read_text()

    assert "service.async_call" not in module
    assert "service.async_call" not in coordinator
    assert "hardware_writes" not in module
    assert not Path("custom_components/kems/agile_alpha840.py").exists()
