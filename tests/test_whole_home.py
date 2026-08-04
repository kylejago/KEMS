"""Tests for combined electricity and gas metrics."""

from kems_core import GasSummary, SimulationState, Snapshot, WholeHomeEngine


def test_whole_home_combines_gas_and_electricity() -> None:
    """Gas should be included in both observed and simulated home totals."""
    result = WholeHomeEngine().summarise(
        Snapshot(electricity_standing_charge=50.0),
        SimulationState(
            actual_cost_pence=200.0,
            simulated_cost_pence=120.0,
            actual_house_consumption_kwh=10.0,
        ),
        GasSummary(available=True, cost_today_pence=90.0, usage_today_kwh=15.0),
    )

    assert result.observed_total_cost_pence == 340.0
    assert result.simulated_total_cost_pence == 260.0
    assert result.simulated_saving_pence == 80.0
    assert result.observed_total_energy_kwh == 25.0
    assert result.gas_energy_share_percent == 60.0
