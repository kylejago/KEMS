"""Combine electricity and gas into whole-home metrics."""

from __future__ import annotations

from .models import GasSummary, SimulationState, Snapshot, WholeHomeSummary


class WholeHomeEngine:
    """Create combined energy and cost totals."""

    def summarise(
        self,
        snapshot: Snapshot,
        simulation: SimulationState,
        gas: GasSummary,
    ) -> WholeHomeSummary:
        """Combine observed gas with observed/simulated electricity."""
        electricity_standing = snapshot.electricity_standing_charge or 0.0
        observed_electricity = (
            simulation.actual_cost_pence + electricity_standing
            if simulation.actual_cost_pence is not None
            else None
        )
        simulated_electricity = (
            simulation.simulated_cost_pence + electricity_standing
            if simulation.simulated_cost_pence is not None
            else None
        )
        gas_cost = gas.cost_today_pence

        observed_total = _sum_available(observed_electricity, gas_cost)
        simulated_total = _sum_available(simulated_electricity, gas_cost)
        saving = (
            observed_total - simulated_total
            if observed_total is not None and simulated_total is not None
            else None
        )

        electricity_kwh = simulation.actual_house_consumption_kwh
        gas_kwh = gas.usage_today_kwh
        total_energy = _sum_available(electricity_kwh, gas_kwh)
        gas_share = (
            100 * gas_kwh / total_energy
            if gas_kwh is not None and total_energy and total_energy > 0
            else None
        )

        return WholeHomeSummary(
            observed_electricity_cost_pence=_round(observed_electricity, 2),
            simulated_electricity_cost_pence=_round(simulated_electricity, 2),
            observed_gas_cost_pence=_round(gas_cost, 2),
            observed_total_cost_pence=_round(observed_total, 2),
            simulated_total_cost_pence=_round(simulated_total, 2),
            simulated_saving_pence=_round(saving, 2),
            observed_electricity_kwh=_round(electricity_kwh, 3),
            observed_gas_kwh=_round(gas_kwh, 3),
            observed_total_energy_kwh=_round(total_energy, 3),
            gas_energy_share_percent=_round(gas_share, 1),
        )


def _sum_available(*values: float | None) -> float | None:
    """Sum present values, returning None when none are present."""
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _round(value: float | None, digits: int) -> float | None:
    """Round optional numeric values."""
    return round(value, digits) if value is not None else None
