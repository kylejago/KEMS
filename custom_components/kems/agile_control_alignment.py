"""Canonical alignment between Agile rolling dispatch, control, and shadow.

The Alpha8 rolling optimiser is the authority for the current battery target.
The presentation/routing layer is the authority for the current simulated
outcome. These helpers create transient views without mutating the financial
or settled-day simulation ledger. Real hardware writes remain blocked.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .kems_core import ControlConfig, ControlState, SimulationState


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


def _rolling_target(
    simulation: SimulationState,
    agile_state: dict[str, Any],
) -> tuple[dict[str, float], dict[str, Any]] | None:
    """Return the exact usable rolling target and its source plan."""
    plan = agile_state.get("rolling_export_plan")
    if (
        not isinstance(plan, dict)
        or not plan.get("available")
        or simulation.saving_session_active
    ):
        return None

    dispatch_mode = str(plan.get("dispatch_mode") or "")
    if dispatch_mode in {"cheap_charge", "happy_hour_charge"}:
        routing = agile_state.get("current_routing_snapshot")
        charge = None
        if isinstance(routing, dict) and routing.get("available"):
            solar_charge = _number(routing.get("solar_to_battery_kw"))
            grid_charge = _number(routing.get("grid_to_battery_kw"))
            if solar_charge is not None or grid_charge is not None:
                charge = max((solar_charge or 0.0) + (grid_charge or 0.0), 0.0)
        if charge is None:
            charge = max(
                _number(simulation.current_simulated_battery_charge_power_kw) or 0.0,
                0.0,
            )
        return (
            {
                "charge_kw": charge,
                "battery_to_home_kw": 0.0,
                "battery_export_kw": 0.0,
                "total_discharge_kw": 0.0,
            },
            plan,
        )

    target_home = _number(plan.get("current_house_battery_kw"))
    target_discharge = _number(plan.get("current_battery_discharge_target_kw"))
    target_export = _number(plan.get("current_battery_export_target_kw"))
    if target_home is None or target_discharge is None or target_export is None:
        return None

    target_home = max(target_home, 0.0)
    target_export = max(target_export, 0.0)
    target_discharge = max(target_discharge, target_home + target_export, 0.0)
    return (
        {
            "charge_kw": 0.0,
            "battery_to_home_kw": target_home,
            "battery_export_kw": target_export,
            "total_discharge_kw": target_discharge,
        },
        plan,
    )


def aligned_agile_control_views(
    simulation: SimulationState,
    agile_state: dict[str, Any],
) -> tuple[SimulationState, SimulationState, dict[str, Any]]:
    """Return transient control-target and shadow-outcome simulation views.

    The helper is deliberately inert when the rolling plan is unavailable or a
    Power Down session is active. Event-specific control keeps its established
    priority path. The original SimulationState remains untouched for finance
    and history.
    """
    rolling = _rolling_target(simulation, agile_state)
    if rolling is None:
        return (
            simulation,
            simulation,
            {
                "active": False,
                "reason": (
                    "rolling target unavailable, incomplete, or event override active"
                ),
            },
        )
    target, plan = rolling

    routing_values = _routing_values(simulation, agile_state)
    shadow_view = _replace_known(simulation, routing_values)

    control_values = dict(routing_values)
    control_values.update(
        {
            "current_simulated_battery_charge_power_kw": target["charge_kw"],
            "current_simulated_battery_to_home_power_kw": target["battery_to_home_kw"],
            "current_simulated_battery_export_power_kw": target["battery_export_kw"],
            "current_simulated_battery_power_kw": (
                target["total_discharge_kw"] - target["charge_kw"]
            ),
            "target_battery_export_power_kw": target["battery_export_kw"],
        }
    )
    control_view = _replace_known(simulation, control_values)

    return (
        control_view,
        shadow_view,
        {
            "active": True,
            "basis": (
                "exact current Agile rolling target + authoritative routing outcome"
            ),
            "dispatch_mode": plan.get("dispatch_mode"),
            "dispatch_action": plan.get("dispatch_action"),
            "target": {key: round(value, 3) for key, value in target.items()},
            "hardware_writes": "blocked",
        },
    )


def align_agile_control_state(
    control: ControlState,
    simulation: SimulationState,
    agile_state: dict[str, Any],
    config: ControlConfig,
) -> ControlState:
    """Make the published ControlState exactly match the current rolling target.

    ControlEngine still supplies the independent safety/context envelope. This
    final reconciliation changes only the battery command target and associated
    explanatory/output fields, then recomputes the simple power-limit safety
    envelope. Hardware permissions are explicitly forced closed.
    """
    rolling = _rolling_target(simulation, agile_state)
    if rolling is None:
        return control
    target, plan = rolling

    solar = max(control.virtual_scenario_solar_power_kw, 0.0)
    total_output = solar + target["total_discharge_kw"]
    target_within_limits = bool(
        target["charge_kw"] <= config.max_charge_kw + 1e-6
        and target["total_discharge_kw"] <= config.max_discharge_kw + 1e-6
        and target["battery_export_kw"] <= config.export_limit_kw + 1e-6
        and not (target["charge_kw"] > 1e-6 and target["total_discharge_kw"] > 1e-6)
        and total_output <= config.inverter_limit_kw + 1e-6
        and not control.site_import_limit_exceeded
    )
    target_soc = _number(plan.get("target_soc_percent"))
    action = str(
        plan.get("dispatch_action")
        or agile_state.get("current_action")
        or "Follow the exact current Agile rolling target"
    )
    dispatch_mode = str(plan.get("dispatch_mode") or "rolling")

    return replace(
        control,
        operating_reason=f"agile_rolling_{dispatch_mode}",
        desired_work_mode=(
            control.desired_work_mode
            if target["charge_kw"] > 0.01
            else ("Feed-in First" if target["battery_export_kw"] > 0.01 else "Self Use")
        ),
        desired_charge_power_kw=round(target["charge_kw"], 3),
        desired_battery_to_home_power_kw=round(target["battery_to_home_kw"], 3),
        desired_battery_export_power_kw=round(target["battery_export_kw"], 3),
        desired_total_discharge_power_kw=round(target["total_discharge_kw"], 3),
        desired_min_soc_percent=(
            control.desired_min_soc_percent
            if target_soc is None
            else round(target_soc, 1)
        ),
        total_kh7_ac_output_kw=round(total_output, 3),
        kh7_output_headroom_kw=round(
            max(config.inverter_limit_kw - total_output, 0.0), 3
        ),
        plan_safe=bool(control.plan_safe and target_within_limits),
        real_backend_available=False,
        commands_permitted=False,
        blocked_reason=(
            control.blocked_reason
            if target_within_limits
            else "Exact Agile rolling target failed the control power envelope"
        ),
        next_action=action,
    )
