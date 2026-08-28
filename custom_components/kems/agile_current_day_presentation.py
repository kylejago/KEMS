"""Expose settled current-day Agile accounting through KEMS headline simulation."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .kems_core import SimulationState


def _number(value: Any) -> float | None:
    """Return one finite numeric value when available."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _today_agile(state: dict[str, Any]) -> dict[str, Any] | None:
    """Return the reconciled current-day Agile period when authoritative."""
    reconciliation = state.get("current_day_settlement_reconciliation")
    if (
        not isinstance(reconciliation, dict)
        or not reconciliation.get("applied")
        or not reconciliation.get("all_accounting_checks_passed")
    ):
        return None
    periods = state.get("periods")
    if not isinstance(periods, dict):
        return None
    today = periods.get("today")
    if not isinstance(today, dict):
        return None
    agile = today.get("agile_smart_export")
    if not isinstance(agile, dict) or not agile.get("ready"):
        return None
    return agile


def _current_routing(state: dict[str, Any]) -> dict[str, Any] | None:
    """Return the final current Agile routing snapshot when authoritative."""
    routing = state.get("current_routing_snapshot")
    if not isinstance(routing, dict) or not routing.get("available"):
        return None
    return routing


def _current_routing_replacements(state: dict[str, Any]) -> dict[str, float]:
    """Project canonical Agile current routing onto SimulationState power fields."""
    routing = _current_routing(state)
    if routing is None:
        return {}

    house = _number(routing.get("simulated_house_load_kw"))
    solar = _number(routing.get("solar_power_kw"))
    grid_import = _number(routing.get("grid_import_kw"))
    grid_export = _number(routing.get("grid_export_kw"))
    solar_to_battery = _number(routing.get("solar_to_battery_kw"))
    grid_to_battery = _number(routing.get("grid_to_battery_kw"))
    battery_to_home = _number(routing.get("battery_to_home_kw"))
    battery_export = _number(routing.get("battery_export_kw"))
    total_discharge = _number(routing.get("total_discharge_kw"))
    kh7_output = _number(routing.get("normalised_kh7_ac_output_kw"))

    battery_charge = None
    if solar_to_battery is not None or grid_to_battery is not None:
        battery_charge = max(solar_to_battery or 0.0, 0.0) + max(
            grid_to_battery or 0.0,
            0.0,
        )

    if total_discharge is None and (
        battery_to_home is not None or battery_export is not None
    ):
        total_discharge = max(battery_to_home or 0.0, 0.0) + max(
            battery_export or 0.0,
            0.0,
        )

    battery_power = None
    if total_discharge is not None or battery_charge is not None:
        battery_power = max(total_discharge or 0.0, 0.0) - max(
            battery_charge or 0.0,
            0.0,
        )

    replacements: dict[str, float] = {}

    def project(field: str, value: float | None) -> None:
        if value is not None:
            replacements[field] = round(value, 3)

    project("current_simulated_house_load_kw", house)
    project("current_simulated_solar_power_kw", solar)
    project("current_simulated_grid_import_kw", grid_import)
    project("current_simulated_grid_export_kw", grid_export)
    project("current_simulated_battery_power_kw", battery_power)
    project("current_simulated_battery_charge_power_kw", battery_charge)
    project("current_simulated_solar_to_battery_power_kw", solar_to_battery)
    project("current_simulated_battery_to_home_power_kw", battery_to_home)
    project("current_simulated_battery_export_power_kw", battery_export)
    project("current_simulated_total_kh7_output_kw", kh7_output)
    if grid_import is not None:
        grid_bypass = max(grid_import - max(grid_to_battery or 0.0, 0.0), 0.0)
        project("current_simulated_grid_bypass_power_kw", grid_bypass)
        project("current_simulated_total_site_import_kw", grid_import)
    project("target_battery_export_power_kw", battery_export)
    return replacements


def reconciled_current_day_simulation(
    simulation: SimulationState,
    state: dict[str, Any],
) -> SimulationState:
    """Return a headline SimulationState on the settled Agile accounting basis.

    The generic proposal replay remains useful as a comparison model, but once
    current-day Agile settlements have passed their accounting checks the KEMS
    headline sensors must describe the same strategy that the rolling planner,
    Energy today card and shadow ledger are using. Current power fields are
    independently projected from the final Agile routing snapshot whenever it is
    available, so every consumer sees one answer for what KEMS is doing now.
    """
    agile = _today_agile(state)
    routing_replacements = _current_routing_replacements(state)
    if agile is None:
        return (
            replace(simulation, **routing_replacements)
            if routing_replacements
            else simulation
        )

    import_cost = _number(agile.get("import_cost_pence"))
    export_income = _number(agile.get("export_income_pence"))
    grid_import = _number(agile.get("grid_import_kwh"))
    grid_export = _number(agile.get("grid_export_kwh"))
    solar_generation = _number(agile.get("solar_generation_kwh"))
    solar_to_home = _number(agile.get("solar_to_home_kwh"))
    solar_to_battery = _number(agile.get("solar_to_battery_kwh"))
    solar_export = _number(agile.get("solar_export_kwh"))
    grid_to_battery = _number(agile.get("grid_to_battery_kwh"))
    battery_to_home = _number(agile.get("battery_to_home_kwh"))
    battery_export = _number(agile.get("battery_export_kwh"))
    soc = _number(agile.get("ending_soc_percent"))

    if import_cost is None or export_income is None:
        return (
            replace(simulation, **routing_replacements)
            if routing_replacements
            else simulation
        )

    bonus = max(simulation.simulated_saving_session_bonus_pence or 0.0, 0.0)
    simulated_cost = round(import_cost - export_income - bonus, 2)
    saving = (
        round(simulation.actual_cost_pence - simulated_cost, 2)
        if simulation.actual_cost_pence is not None
        else None
    )
    baseline = simulation.baseline_no_system_cost_pence
    avoided_import_value = (
        round(baseline - import_cost, 2) if baseline is not None else None
    )
    system_value = (
        round(avoided_import_value + export_income + bonus, 2)
        if avoided_import_value is not None
        else saving
    )
    battery_charge = (
        round((solar_to_battery or 0.0) + (grid_to_battery or 0.0), 3)
        if solar_to_battery is not None or grid_to_battery is not None
        else simulation.simulated_battery_charge_kwh
    )

    plan = state.get("rolling_export_plan")
    plan = plan if isinstance(plan, dict) and plan.get("available") else {}
    exportable = _number(plan.get("exportable_battery_energy_kwh"))
    reserved = _number(plan.get("protected_house_energy_kwh"))
    projected_soc = _number(plan.get("projected_soc_at_cheap_period_percent"))
    weighted_rate = _number(agile.get("weighted_achieved_export_rate_pence"))

    replacements: dict[str, Any] = {
        "simulated_cost_pence": simulated_cost,
        "saving_pence": saving,
        "simulated_import_cost_pence": round(import_cost, 2),
        "simulated_export_income_pence": round(export_income, 2),
        "simulated_grid_import_kwh": (
            round(grid_import, 3)
            if grid_import is not None
            else simulation.simulated_grid_import_kwh
        ),
        "simulated_grid_export_kwh": (
            round(grid_export, 3)
            if grid_export is not None
            else simulation.simulated_grid_export_kwh
        ),
        "simulated_solar_generation_kwh": (
            round(solar_generation, 3)
            if solar_generation is not None
            else simulation.simulated_solar_generation_kwh
        ),
        "simulated_solar_to_home_kwh": (
            round(solar_to_home, 3)
            if solar_to_home is not None
            else simulation.simulated_solar_to_home_kwh
        ),
        "simulated_solar_to_battery_kwh": (
            round(solar_to_battery, 3)
            if solar_to_battery is not None
            else simulation.simulated_solar_to_battery_kwh
        ),
        "simulated_solar_export_kwh": (
            round(solar_export, 3)
            if solar_export is not None
            else simulation.simulated_solar_export_kwh
        ),
        "simulated_grid_to_battery_kwh": (
            round(grid_to_battery, 3)
            if grid_to_battery is not None
            else simulation.simulated_grid_to_battery_kwh
        ),
        "simulated_battery_charge_kwh": battery_charge,
        "simulated_battery_to_home_kwh": (
            round(battery_to_home, 3)
            if battery_to_home is not None
            else simulation.simulated_battery_to_home_kwh
        ),
        "simulated_battery_export_kwh": (
            round(battery_export, 3)
            if battery_export is not None
            else simulation.simulated_battery_export_kwh
        ),
        "simulated_battery_soc": (
            round(soc, 1) if soc is not None else simulation.simulated_battery_soc
        ),
        "avoided_day_rate_import_kwh": (
            round(battery_to_home, 3)
            if battery_to_home is not None
            else simulation.avoided_day_rate_import_kwh
        ),
        "simulated_avoided_import_value_pence": avoided_import_value,
        "simulated_system_value_pence": system_value,
        "effective_export_rate_pence": (
            round(weighted_rate, 4)
            if weighted_rate is not None
            else simulation.effective_export_rate_pence
        ),
        "exportable_battery_energy_kwh": (
            round(exportable, 3)
            if exportable is not None
            else simulation.exportable_battery_energy_kwh
        ),
        "reserved_for_home_kwh": (
            round(reserved, 3)
            if reserved is not None
            else simulation.reserved_for_home_kwh
        ),
        "projected_soc_at_cheap_period_percent": (
            round(projected_soc, 1)
            if projected_soc is not None
            else simulation.projected_soc_at_cheap_period_percent
        ),
    }
    replacements.update(routing_replacements)
    return replace(simulation, **replacements)
