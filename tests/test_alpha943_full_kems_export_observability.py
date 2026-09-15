"""Regression coverage for Alpha9.43 Full KEMS export observability."""

from __future__ import annotations

from custom_components.kems.kems_core import SimulationState
from custom_components.kems.kems_core.observability import (
    full_kems_battery_export_present,
)


def test_full_kems_export_sensor_uses_customer_simulation_authority() -> None:
    """Live no-export policy must not hide completed Full KEMS battery export."""
    simulation = SimulationState(
        ready=True,
        battery_export_enabled=False,
        no_export_mode_active=True,
        export_tariff_active=False,
        simulated_battery_export_kwh=17.035,
        current_simulated_battery_export_power_kw=0.0,
        target_battery_export_power_kw=0.0,
    )

    assert full_kems_battery_export_present(simulation) is True


def test_full_kems_export_sensor_is_off_when_ready_model_contains_no_export() -> None:
    """A ready Full KEMS model with no export evidence must report off."""
    simulation = SimulationState(
        ready=True,
        simulated_battery_export_kwh=0.0,
        current_simulated_battery_export_power_kw=0.0,
        target_battery_export_power_kw=0.0,
    )

    assert full_kems_battery_export_present(simulation) is False


def test_full_kems_export_sensor_is_unavailable_until_simulation_is_ready() -> None:
    """Do not infer export observability before the customer simulation is ready."""
    simulation = SimulationState(
        ready=False,
        simulated_battery_export_kwh=17.035,
    )

    assert full_kems_battery_export_present(simulation) is None
