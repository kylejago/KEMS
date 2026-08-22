"""Alpha 7.24 Agile shadow outcome parity.

Alpha 7.23 proved optimiser-to-command parity and the independent 13-point
shadow safety envelope. Alpha 7.24 closes the pre-install routing mismatch that
appears when the live snapshot has no physical PV source but the Agile replay is
using the proposal-solar model.

The rolling planner now derives current house battery headroom from the same
``SimulationEngine._simulated_solar_power`` path used by the Agile replay. The
shadow adapter also normalises inverter AC output from the digital-twin routed
AC output instead of counting solar sent to the battery as AC output.

This remains simulation/shadow only. It never calls a Home Assistant service,
never exposes a FoxESS write path, and never permits hardware commands.
"""

# ruff: noqa: E501

from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import agile_alpha723_shadow as alpha723
from . import agile_rolling_replan as rolling
from .kems_core import ControlConfig, ControlState, SimulationConfig, SimulationState


def _number(value: Any) -> float | None:
    """Return one float when possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _routing_snapshot(simulation: SimulationState) -> dict[str, float | None]:
    """Return the current proposal/live digital-twin routing context."""
    house = _number(simulation.current_simulated_house_load_kw)
    solar = _number(simulation.current_simulated_solar_power_kw)
    solar_to_battery = _number(simulation.current_simulated_solar_to_battery_power_kw)
    battery_home = _number(simulation.current_simulated_battery_to_home_power_kw)
    battery_export = _number(simulation.current_simulated_battery_export_power_kw)
    ac_output = _number(simulation.current_simulated_total_kh7_output_kw)
    return {
        "house_load_kw": None if house is None else round(max(house, 0.0), 3),
        "solar_power_kw": None if solar is None else round(max(solar, 0.0), 3),
        "solar_to_battery_kw": (
            None if solar_to_battery is None else round(max(solar_to_battery, 0.0), 3)
        ),
        "battery_to_home_kw": (
            None if battery_home is None else round(max(battery_home, 0.0), 3)
        ),
        "battery_export_kw": (
            None if battery_export is None else round(max(battery_export, 0.0), 3)
        ),
        "total_kh7_ac_output_kw": (
            None if ac_output is None else round(max(ac_output, 0.0), 3)
        ),
    }


def build_agile_shadow_command_with_outcome_parity(
    control: ControlState,
    simulation: SimulationState,
    config: ControlConfig,
    agile_state: dict[str, Any],
) -> tuple[ControlState | None, dict[str, Any]]:
    """Build the Alpha7.23 command and normalise routed AC output.

    Battery discharge/export targets remain the exact optimiser outputs. Only
    the AC-output accounting is corrected: start from the digital twin's routed
    AC output, remove its battery-discharge contribution, then add the Agile
    candidate's exact discharge target. This avoids treating solar routed into
    the battery as inverter AC output while preserving the safety validator's
    ability to reject a genuine over-limit battery request.
    """
    candidate, context = _ORIGINAL_BUILD(
        control,
        simulation,
        config,
        agile_state,
    )
    if candidate is None:
        return None, context

    routing = _routing_snapshot(simulation)
    base_ac = routing.get("total_kh7_ac_output_kw")
    base_home = routing.get("battery_to_home_kw") or 0.0
    base_export = routing.get("battery_export_kw") or 0.0
    base_discharge = max(float(base_home) + float(base_export), 0.0)
    candidate_discharge = max(float(candidate.desired_total_discharge_power_kw), 0.0)

    if base_ac is not None:
        normalised_ac = max(float(base_ac) - base_discharge + candidate_discharge, 0.0)
        basis = "digital_twin_ac_output_substitute_candidate_discharge"
    else:
        solar = routing.get("solar_power_kw") or 0.0
        solar_to_battery = routing.get("solar_to_battery_kw") or 0.0
        routed_solar_ac = max(float(solar) - float(solar_to_battery), 0.0)
        normalised_ac = routed_solar_ac + candidate_discharge
        basis = "solar_ac_minus_battery_charge_plus_candidate_discharge"

    candidate = replace(
        candidate,
        total_kh7_ac_output_kw=round(normalised_ac, 3),
        kh7_output_headroom_kw=round(
            max(config.inverter_limit_kw - normalised_ac, 0.0),
            3,
        ),
    )
    context = {
        **context,
        "outcome_routing": {
            "basis": basis,
            **routing,
            "base_digital_twin_discharge_kw": round(base_discharge, 3),
            "candidate_discharge_kw": round(candidate_discharge, 3),
            "normalised_candidate_ac_output_kw": round(normalised_ac, 3),
        },
    }
    return candidate, context


def evaluate_agile_shadow_command_with_outcome_parity(
    control: ControlState,
    simulation: SimulationState,
    config: ControlConfig,
    agile_state: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate Alpha7.23 command parity plus routed digital-twin outcome parity."""
    result = _ORIGINAL_EVALUATE(control, simulation, config, agile_state)
    tracking = result.get("tracking")
    if not isinstance(tracking, dict):
        return result

    within = tracking.get("within_tolerance")
    checked = (
        [value for value in within.values() if value is not None]
        if isinstance(within, dict)
        else []
    )
    outcome_passed = bool(checked and all(bool(value) for value in checked))
    result["outcome_parity"] = {
        "passed": outcome_passed,
        "basis": tracking.get("basis"),
        "tracking_score_percent": tracking.get("tracking_score_percent"),
        "within_tolerance": within,
    }
    result["outcome_parity_passed"] = outcome_passed

    if (
        result.get("parity_passed")
        and (result.get("safety") or {}).get("passed")
        and checked
        and not outcome_passed
    ):
        result["status"] = "CHECK — shadow outcome mismatch"
    return result


def _record_agile_decision_with_outcome(self, result: dict[str, Any], now) -> None:
    """Add Alpha7.24 outcome parity to the existing compact decision evidence."""
    _ORIGINAL_RECORD(self, result, now)
    decisions = getattr(self, "_agile_decisions", None)
    if not isinstance(decisions, list) or not decisions:
        return
    latest = decisions[-1]
    if latest.get("timestamp") != now.isoformat():
        return
    tracking = result.get("tracking") or {}
    latest["tracking_score_percent"] = tracking.get("tracking_score_percent")
    latest["outcome_parity_passed"] = bool(result.get("outcome_parity_passed"))
    latest["outcome_routing_basis"] = (result.get("outcome_routing") or {}).get("basis")
    self._dirty = True


_ALPHA724_DASHBOARD_CARDS = r"""      - type: entities
        title: Agile shadow-command parity
        show_header_toggle: false
        entities:
          - entity: sensor.kems_agile_shadow_status
            name: Agile shadow status
          - entity: sensor.kems_agile_shadow_safety
            name: Independent safety
          - entity: sensor.kems_agile_shadow_command
            name: Desired inverter mode
          - entity: sensor.kems_agile_shadow_target_export
            name: Target battery export
          - entity: sensor.kems_agile_shadow_target_total_discharge
            name: Target total discharge
      - type: markdown
        title: Agile optimiser → shadow command → outcome
        content: |
          {% set s = states.sensor.kems_agile_shadow_status %}
          {% set c = states.sensor.kems_agile_shadow_command %}
          {% set safe = states.sensor.kems_agile_shadow_safety %}
          {% set tracking = s.attributes.tracking if s else {} %}
          {% set outcome = s.attributes.outcome_parity if s else {} %}
          {% set routing = s.attributes.outcome_routing if s else {} %}
          **Status:** **{{ s.state if s else 'Unavailable' }}**  
          **Dispatch:** {{ s.attributes.dispatch_mode if s else '—' }}  
          **Action:** {{ s.attributes.dispatch_action if s else '—' }}  
          **Price horizon:** {{ s.attributes.price_horizon_status if s else '—' }}  
          **Missing prices:** {{ (s.attributes.price_horizon_missing_labels if s else []) | join(', ') or 'None' }}  
          **Outcome parity:** **{{ 'PASS' if outcome.passed else 'CHECK' }}**  
          **Tracking score:** {{ tracking.tracking_score_percent if tracking.tracking_score_percent is not none else '—' }}%  
          **Routing basis:** {{ routing.basis if routing else '—' }}  
          **Hardware writes:** **BLOCKED**

          | Command | KEMS target |
          |---|---:|
          | Work mode | {{ c.state if c else '—' }} |
          | Battery → home | {{ c.attributes.battery_to_home_kw if c else '—' }} kW |
          | Battery → export | {{ c.attributes.battery_export_kw if c else '—' }} kW |
          | Total discharge | {{ c.attributes.total_discharge_kw if c else '—' }} kW |
          | KH7 AC output | {{ c.attributes.total_kh7_ac_output_kw if c else '—' }} kW |
          | Minimum SOC | {{ c.attributes.minimum_soc_percent if c else '—' }}% |
          | Independent safety | {{ safe.state if safe else '—' }} |

          Alpha7.24 keeps the raw rolling Agile optimiser target auditable, uses proposal/live solar-aware house headroom, normalises AC output from routed digital-twin power, and still passes the resulting candidate through the independent 13-point shadow safety envelope. It is not sent to FoxESS.
"""


_ORIGINAL_BUILD = alpha723.build_agile_shadow_command
_ORIGINAL_EVALUATE = alpha723.evaluate_agile_shadow_command
_ORIGINAL_RECORD = alpha723._record_agile_decision


def install_alpha724_outcome_parity_patch() -> None:
    """Install proposal-solar-aware headroom and shadow outcome parity once."""
    headroom = rolling._current_house_headroom_kw
    if not getattr(headroom, "_kems_alpha724_outcome", False):
        original_headroom = headroom

        def proposal_solar_house_headroom(self, config: SimulationConfig) -> float:
            records = getattr(self, "_panel_today_records", [])
            if not records:
                return original_headroom(self, config)
            current = records[-1]
            house = max(_number(getattr(current, "house_load_kw", None)) or 0.0, 0.0)
            simulator = getattr(self, "_simulation", None)
            if simulator is None or not hasattr(simulator, "_simulated_solar_power"):
                return original_headroom(self, config)
            solar = max(float(simulator._simulated_solar_power(current, config)), 0.0)
            headroom_kw = min(
                max(house - solar, 0.0),
                max(config.max_discharge_kw, 0.0),
            )
            self._kems_alpha724_house_headroom = {
                "basis": "same proposal/live solar path as Agile replay",
                "house_load_kw": round(house, 3),
                "effective_solar_kw": round(solar, 3),
                "battery_house_headroom_kw": round(headroom_kw, 3),
            }
            return headroom_kw

        proposal_solar_house_headroom._kems_alpha724_outcome = True
        rolling._current_house_headroom_kw = proposal_solar_house_headroom

    if (
        alpha723.build_agile_shadow_command
        is not build_agile_shadow_command_with_outcome_parity
    ):
        alpha723.build_agile_shadow_command = (
            build_agile_shadow_command_with_outcome_parity
        )

    if (
        alpha723.evaluate_agile_shadow_command
        is not evaluate_agile_shadow_command_with_outcome_parity
    ):
        alpha723.evaluate_agile_shadow_command = (
            evaluate_agile_shadow_command_with_outcome_parity
        )

    if alpha723._record_agile_decision is not _record_agile_decision_with_outcome:
        alpha723._record_agile_decision = _record_agile_decision_with_outcome

    alpha723._AGILE_DASHBOARD_CARDS = _ALPHA724_DASHBOARD_CARDS
