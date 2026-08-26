"""Canonical alignment between Agile rolling dispatch, control, and shadow.

The Alpha8 rolling optimiser is the authority for the current battery target.
The presentation/routing layer is the authority for the current simulated
outcome.  These helpers create transient SimulationState views for the
ControlEngine and shadow validator without mutating the financial/day ledger.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .kems_core import SimulationState


def _number(value: Any) -> float | None:
    """Return a finite float for one optional diagnostic value."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _routing_values(
    simulation: SimulationState,
    agile_state: dict[str, Any],
) -> dict[str, float | None]:
    """Return authoritative current routing values with safe fallbacks."""
    routing = agile_state.get("current_routing_snapshot")
    if not isinstance(routing, dict) or not routing.get("available"):
        return {}

    solar_to_battery = _number(routing.get("solar_to_battery_kw"))
    grid_to_battery = _number(routing.get("grid_to_battery_kw"))
    charge = (
        max((solar_to_battery or 0.0) + (grid_to_battery or 0.0), 0.0)
        if solar_to_battery is not None or grid_to_battery is not None
        else simulation.current_simulated_battery_charge_power_kw
    )
    battery_home = _number(routing.get("battery_to_home_kw"))
    battery_export = _number(routing.get("battery_export_kw"))
    discharge = (
        max((battery_home or 0.0) + (battery_export or 0.0), 0.0)
        if battery_home is not None or battery_export is not None
        else None
    )
    battery_power = (
        discharge - max(charge or 0.0, 0.0) if discharge is not None else None
    )

    return {
        "current_simulated_house_load_kw": _number(
            routing.get("simulated_house_load_kw")
        ),
        "current_simulated_solar_power_kw": _number(routing.get("solar_power_kw")),
        "current_simulated_grid_import_kw": _number(routing.get("grid_import_kw")),
        "current_simulated_grid_export_kw": _number(routing.get("grid_export_kw")),
        "current_simulated_battery_power_kw": battery_power,
        "current_simulated_battery_charge_power_kw": charge,
        "current_simulated_solar_to_battery_power_kw": solar_to_battery,
        "current_simulated_battery_to_home_power_kw": battery_home,
        "current_simulated_battery_export_power_kw": battery_export,
        "current_simulated_total_kh7_output_kw": _number(
            routing.get("normalised_kh7_ac_output_kw")
        ),
        "current_simulated_grid_bypass_power_kw": _number(
            routing.get("grid_import_kw")
        ),
        "current_simulated_total_site_import_kw": _number(
            routing.get("grid_import_kw")
        ),
    }


def _replace_known(
    simulation: SimulationState,
    values: dict[str, float | None],
) -> SimulationState:
    """Replace only values supplied by the authoritative runtime layer."""
    supplied = {key: value for key, value in values.items() if value is not None}
    return replace(simulation, **supplied) if supplied else simulation


def aligned_agile_control_views(
    simulation: SimulationState,
    agile_state: dict[str, Any],
) -> tuple[SimulationState, SimulationState, dict[str, Any]]:
    """Return transient control-target and shadow-outcome simulation views.

    The helper is deliberately inert when the rolling plan is unavailable or a
    Power Down session is active. Event-specific control keeps its established
    priority path. The returned original SimulationState remains suitable for
    finance/history and is never mutated.
    """
    plan = agile_state.get("rolling_export_plan")
    if (
        not isinstance(plan, dict)
        or not plan.get("available")
        or simulation.saving_session_active
    ):
        return simulation, simulation, {
            "active": False,
            "reason": "rolling target unavailable or event override active",
        }

    target_home = _number(plan.get("current_house_battery_kw"))
    target_discharge = _number(plan.get("current_battery_discharge_target_kw"))
    target_export = _number(plan.get("current_battery_export_target_kw"))
    if target_home is None or target_discharge is None or target_export is None:
        return simulation, simulation, {
            "active": False,
            "reason": "rolling target is incomplete",
        }

    target_home = max(target_home, 0.0)
    target_export = max(target_export, 0.0)
    target_discharge = max(target_discharge, target_home + target_export, 0.0)

    routing_values = _routing_values(simulation, agile_state)
    shadow_view = _replace_known(simulation, routing_values)

    control_values = dict(routing_values)
    control_values.update(
        {
            "current_simulated_battery_to_home_power_kw": target_home,
            "current_simulated_battery_export_power_kw": target_export,
            "current_simulated_battery_power_kw": target_discharge,
            "target_battery_export_power_kw": target_export,
        }
    )
    control_view = _replace_known(simulation, control_values)

    return control_view, shadow_view, {
        "active": True,
        "basis": "exact current Agile rolling target + authoritative routing outcome",
        "dispatch_mode": plan.get("dispatch_mode"),
        "dispatch_action": plan.get("dispatch_action"),
        "target": {
            "battery_to_home_kw": round(target_home, 3),
            "battery_export_kw": round(target_export, 3),
            "total_discharge_kw": round(target_discharge, 3),
        },
        "hardware_writes": "blocked",
    }
