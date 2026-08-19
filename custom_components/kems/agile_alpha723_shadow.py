"""Alpha 7.23 Agile optimiser to shadow-command parity.

This module deliberately remains on the safe side of the KEMS control boundary.
It converts the live Agile rolling plan into the same ``ControlState`` command
shape used by the existing independent shadow validator, publishes the result,
and retains compact decision evidence. It never calls a Home Assistant service
and never exposes a real FoxESS backend.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import dashboard as dashboard_module
from . import shadow_validation as shadow_module
from .kems_core import ControlConfig, ControlState, SimulationState
from .kems_core.shadow_validation import (
    shadow_plan_vs_outcome,
    validate_shadow_command,
)

MAX_AGILE_DECISIONS = 250

_AGILE_ENTITY_IDS = (
    "sensor.kems_agile_shadow_status",
    "sensor.kems_agile_shadow_command",
    "sensor.kems_agile_shadow_safety",
    "sensor.kems_agile_shadow_target_export",
    "sensor.kems_agile_shadow_target_total_discharge",
)


def _number(value: Any) -> float | None:
    """Return one finite-ish float when possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_agile_shadow_command(
    control: ControlState,
    simulation: SimulationState,
    config: ControlConfig,
    agile_state: dict[str, Any],
) -> tuple[ControlState | None, dict[str, Any]]:
    """Convert the current rolling Agile target into a hardware-shaped command.

    The optimiser target is not clipped here. If it asks for something outside
    the configured command envelope, the existing 13-point validator must see
    and reject that exact target rather than this adapter silently correcting it.
    """
    plan = agile_state.get("rolling_export_plan")
    if not isinstance(plan, dict) or not plan.get("available"):
        return None, {
            "available": False,
            "status": "Waiting for Agile rolling plan",
            "reason": (
                plan.get("reason")
                if isinstance(plan, dict)
                else "rolling_export_plan unavailable"
            ),
            "hardware_writes": "blocked",
        }

    discharge = _number(plan.get("current_battery_discharge_target_kw"))
    export = _number(plan.get("current_battery_export_target_kw"))
    house = _number(plan.get("current_house_battery_kw"))
    if discharge is None or export is None:
        return None, {
            "available": False,
            "status": "Waiting for current Agile dispatch target",
            "dispatch_mode": plan.get("dispatch_mode"),
            "hardware_writes": "blocked",
        }

    discharge = max(discharge, 0.0)
    export = max(export, 0.0)
    house = max(house if house is not None else discharge - export, 0.0)
    target_soc = _number(plan.get("target_soc_percent"))
    target_soc = (
        config.normal_reserve_percent if target_soc is None else target_soc
    )
    solar = max(
        _number(getattr(simulation, "current_simulated_solar_power_kw", None)) or 0.0,
        0.0,
    )
    total_output = solar + discharge
    horizon_held = bool(plan.get("price_horizon_battery_export_held"))
    horizon_complete = plan.get("price_horizon_complete")
    deadline_override = bool(plan.get("price_horizon_deadline_override"))
    dispatch_mode = str(plan.get("dispatch_mode") or "unavailable")
    action = str(
        plan.get("dispatch_action")
        or agile_state.get("current_action")
        or "Follow Agile rolling dispatch target"
    )

    candidate = replace(
        control,
        operating_reason=f"agile_shadow_{dispatch_mode}",
        desired_work_mode="Feed-in First" if export > 0.01 else "Self Use",
        desired_charge_power_kw=0.0,
        desired_battery_to_home_power_kw=round(house, 3),
        desired_battery_export_power_kw=round(export, 3),
        desired_total_discharge_power_kw=round(discharge, 3),
        desired_min_soc_percent=round(target_soc, 1),
        desired_grid_export_allowed=export > 0.01,
        total_kh7_ac_output_kw=round(total_output, 3),
        kh7_output_headroom_kw=round(
            max(config.inverter_limit_kw - total_output, 0.0), 3
        ),
        real_backend_available=False,
        commands_permitted=False,
        blocked_reason="Agile shadow only — real FoxESS writes are hard-blocked",
        next_action=action,
    )

    parity = {
        "export_target_matches_optimizer": abs(
            candidate.desired_battery_export_power_kw - export
        )
        <= 0.001,
        "discharge_target_matches_optimizer": abs(
            candidate.desired_total_discharge_power_kw - discharge
        )
        <= 0.001,
        "house_target_matches_optimizer": abs(
            candidate.desired_battery_to_home_power_kw - house
        )
        <= 0.001,
        "horizon_hold_forces_zero_export": (
            not horizon_held or candidate.desired_battery_export_power_kw <= 0.001
        ),
    }
    parity_passed = all(parity.values())
    context = {
        "available": True,
        "status": "Candidate ready" if parity_passed else "Parity failure",
        "dispatch_mode": dispatch_mode,
        "dispatch_action": action,
        "price_horizon_complete": horizon_complete,
        "price_horizon_status": plan.get("price_horizon_status"),
        "price_horizon_missing_labels": plan.get("price_horizon_missing_labels"),
        "battery_export_held": horizon_held,
        "deadline_override": deadline_override,
        "target_soc_percent": round(target_soc, 1),
        "simulated_soc_percent": plan.get("simulated_soc_percent"),
        "exportable_battery_energy_kwh": plan.get("exportable_battery_energy_kwh"),
        "protected_house_energy_kwh": plan.get("protected_house_energy_kwh"),
        "planned_battery_export_kwh": plan.get("planned_battery_export_kwh"),
        "optimizer_target": {
            "battery_to_home_kw": round(house, 3),
            "battery_export_kw": round(export, 3),
            "total_discharge_kw": round(discharge, 3),
        },
        "parity": parity,
        "parity_passed": parity_passed,
        "hardware_writes": "blocked",
        "real_backend_available": False,
    }
    return candidate, context


def evaluate_agile_shadow_command(
    control: ControlState,
    simulation: SimulationState,
    config: ControlConfig,
    agile_state: dict[str, Any],
) -> dict[str, Any]:
    """Build, independently validate, and compare the Agile shadow candidate."""
    candidate, context = build_agile_shadow_command(
        control,
        simulation,
        config,
        agile_state,
    )
    if candidate is None:
        return context

    safety = validate_shadow_command(candidate, config)
    tracking = shadow_plan_vs_outcome(candidate, simulation)
    target = tracking.get("target", {})
    if not context.get("parity_passed"):
        status = "BLOCKED — optimiser/command parity"
    elif not safety.get("passed"):
        status = "BLOCKED — shadow safety validation"
    elif context.get("battery_export_held"):
        status = "PASS — price-horizon hold"
    elif context.get("deadline_override"):
        status = "PASS — deadline override"
    else:
        status = "PASS — shadow candidate ready"

    return {
        **context,
        "status": status,
        "candidate": {
            "desired_work_mode": candidate.desired_work_mode,
            "charge_kw": candidate.desired_charge_power_kw,
            "battery_to_home_kw": candidate.desired_battery_to_home_power_kw,
            "battery_export_kw": candidate.desired_battery_export_power_kw,
            "total_discharge_kw": candidate.desired_total_discharge_power_kw,
            "minimum_soc_percent": candidate.desired_min_soc_percent,
            "grid_export_allowed": candidate.desired_grid_export_allowed,
            "total_kh7_ac_output_kw": candidate.total_kh7_ac_output_kw,
            "data_fresh": candidate.data_fresh,
            "plan_safe": candidate.plan_safe,
            "commands_permitted": False,
        },
        "target": target,
        "safety": safety,
        "tracking": tracking,
        "safe_to_shadow": bool(context.get("parity_passed") and safety.get("passed")),
        "safe_to_write_hardware": False,
    }


def _record_agile_decision(self, result: dict[str, Any], now) -> None:
    """Retain compact Agile command changes in the existing shadow store."""
    decisions = getattr(self, "_agile_decisions", None)
    if not isinstance(decisions, list):
        decisions = []
        self._agile_decisions = decisions
    target = result.get("target") or result.get("optimizer_target") or {}
    signature = (
        result.get("status"),
        result.get("dispatch_mode"),
        target.get("charge_kw"),
        target.get("battery_to_home_kw"),
        target.get("battery_export_kw"),
        target.get("total_discharge_kw"),
        result.get("price_horizon_status"),
        tuple(result.get("price_horizon_missing_labels") or []),
    )
    if signature == getattr(self, "_last_agile_signature", None):
        return
    self._last_agile_signature = signature
    decisions.append(
        {
            "timestamp": now.isoformat(),
            "status": result.get("status"),
            "dispatch_mode": result.get("dispatch_mode"),
            "dispatch_action": result.get("dispatch_action"),
            "target": dict(target),
            "safety_passed": bool((result.get("safety") or {}).get("passed")),
            "parity_passed": bool(result.get("parity_passed")),
            "battery_export_held": bool(result.get("battery_export_held")),
            "deadline_override": bool(result.get("deadline_override")),
            "price_horizon_missing_labels": list(
                result.get("price_horizon_missing_labels") or []
            ),
        }
    )
    self._agile_decisions = decisions[-MAX_AGILE_DECISIONS:]
    self._dirty = True


def _publish_agile_shadow(self, result: dict[str, Any], now) -> None:
    """Publish first-class HA state for the Agile shadow command."""
    common = {
        "mode": "simulation_shadow_only",
        "hardware_writes": "blocked",
        "real_backend_available": False,
        "generated_at": now.isoformat(),
    }
    self._set(
        "sensor.kems_agile_shadow_status",
        result.get("status", "Unavailable"),
        {
            "friendly_name": "KEMS Agile shadow command status",
            **result,
            "recent_decisions": list(getattr(self, "_agile_decisions", []))[-20:],
            **common,
        },
    )
    candidate = result.get("candidate") or {}
    self._set(
        "sensor.kems_agile_shadow_command",
        candidate.get("desired_work_mode", "Unavailable"),
        {
            "friendly_name": "KEMS Agile shadow command",
            **candidate,
            "dispatch_mode": result.get("dispatch_mode"),
            "dispatch_action": result.get("dispatch_action"),
            "optimizer_target": result.get("optimizer_target"),
            "parity": result.get("parity"),
            "parity_passed": result.get("parity_passed"),
            **common,
        },
    )
    safety = result.get("safety") or {}
    self._set(
        "sensor.kems_agile_shadow_safety",
        "PASS" if safety.get("passed") else "FAIL" if safety else "Waiting",
        {
            "friendly_name": "KEMS Agile independent shadow safety",
            **safety,
            "safe_to_write_hardware": False,
            **common,
        },
    )
    self._set(
        "sensor.kems_agile_shadow_target_export",
        candidate.get("battery_export_kw", "Unavailable"),
        {
            "friendly_name": "KEMS Agile shadow target battery export",
            "unit_of_measurement": "kW",
            "battery_export_held": result.get("battery_export_held"),
            "deadline_override": result.get("deadline_override"),
            **common,
        },
    )
    self._set(
        "sensor.kems_agile_shadow_target_total_discharge",
        candidate.get("total_discharge_kw", "Unavailable"),
        {
            "friendly_name": "KEMS Agile shadow target total discharge",
            "unit_of_measurement": "kW",
            "dispatch_mode": result.get("dispatch_mode"),
            **common,
        },
    )


_AGILE_DASHBOARD_CARDS = r"""      - type: entities
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
        title: Agile optimiser → shadow command
        content: |
          {% set s = states.sensor.kems_agile_shadow_status %}
          {% set c = states.sensor.kems_agile_shadow_command %}
          {% set safe = states.sensor.kems_agile_shadow_safety %}
          **Status:** **{{ s.state if s else 'Unavailable' }}**  
          **Dispatch:** {{ s.attributes.dispatch_mode if s else '—' }}  
          **Action:** {{ s.attributes.dispatch_action if s else '—' }}  
          **Price horizon:** {{ s.attributes.price_horizon_status if s else '—' }}  
          **Missing prices:** {{ (s.attributes.price_horizon_missing_labels if s else []) | join(', ') or 'None' }}  
          **Hardware writes:** **BLOCKED**

          | Command | KEMS target |
          |---|---:|
          | Work mode | {{ c.state if c else '—' }} |
          | Battery → home | {{ c.attributes.battery_to_home_kw if c else '—' }} kW |
          | Battery → export | {{ c.attributes.battery_export_kw if c else '—' }} kW |
          | Total discharge | {{ c.attributes.total_discharge_kw if c else '—' }} kW |
          | Minimum SOC | {{ c.attributes.minimum_soc_percent if c else '—' }}% |
          | Independent safety | {{ safe.state if safe else '—' }} |

          The candidate is copied from the **live rolling Agile optimiser** and passed through the same 13-point independent shadow safety envelope. It is not sent to FoxESS.
"""


def _inject_after_cards(content: str, path: str, cards: str) -> str:
    path_marker = f"    path: {path}\n"
    start = content.find(path_marker)
    if start < 0:
        return content
    cards_marker = "    cards:\n"
    cards_at = content.find(cards_marker, start)
    if cards_at < 0:
        return content
    insert_at = cards_at + len(cards_marker)
    if "title: Agile shadow-command parity" in content[start : start + 6000]:
        return content
    return content[:insert_at] + cards.rstrip() + "\n" + content[insert_at:]


def install_alpha723_shadow_patch() -> None:
    """Install additive Agile shadow parity, persistence, and dashboard telemetry."""
    load = shadow_module.ShadowValidationRecorder.async_load
    if not getattr(load, "_kems_alpha723_agile", False):
        original_load = load

        async def load_with_agile(self) -> None:
            await original_load(self)
            data = await self._store.async_load() or {}
            decisions = data.get("agile_decisions", [])
            self._agile_decisions = (
                [dict(item) for item in decisions if isinstance(item, dict)][
                    -MAX_AGILE_DECISIONS:
                ]
                if isinstance(decisions, list)
                else []
            )

        load_with_agile._kems_alpha723_agile = True
        shadow_module.ShadowValidationRecorder.async_load = load_with_agile

    save = shadow_module.ShadowValidationRecorder.async_save
    if not getattr(save, "_kems_alpha723_agile", False):

        async def save_with_agile(self) -> None:
            if not self._dirty:
                return
            await self._store.async_save(
                {
                    "settled_half_hours": self._settled[-shadow_module.MAX_SETTLED_SLOTS :],
                    "decisions": self._decisions[-shadow_module.MAX_DECISIONS :],
                    "agile_decisions": list(getattr(self, "_agile_decisions", []))[
                        -MAX_AGILE_DECISIONS:
                    ],
                }
            )
            self._dirty = False

        save_with_agile._kems_alpha723_agile = True
        shadow_module.ShadowValidationRecorder.async_save = save_with_agile

    update = shadow_module.ShadowValidationRecorder.async_update
    if not getattr(update, "_kems_alpha723_agile", False):
        original_update = update

        async def update_with_agile(
            self,
            *,
            snapshot,
            simulation,
            control,
            now,
            config,
            agile_state,
        ):
            agile_result = evaluate_agile_shadow_command(
                control,
                simulation,
                config,
                agile_state,
            )
            _record_agile_decision(self, agile_result, now)
            await original_update(
                self,
                snapshot=snapshot,
                simulation=simulation,
                control=control,
                now=now,
                config=config,
                agile_state=agile_state,
            )
            self._state["agile_shadow"] = dict(agile_result)
            self._state["agile_shadow"]["recent_decisions"] = list(
                getattr(self, "_agile_decisions", [])
            )[-20:]
            _publish_agile_shadow(self, agile_result, now)
            return self.state

        update_with_agile._kems_alpha723_agile = True
        shadow_module.ShadowValidationRecorder.async_update = update_with_agile

    shutdown = shadow_module.ShadowValidationRecorder.async_shutdown
    if not getattr(shutdown, "_kems_alpha723_agile", False):
        original_shutdown = shutdown

        async def shutdown_with_agile(self) -> None:
            await original_shutdown(self)
            for entity_id in _AGILE_ENTITY_IDS:
                self._hass.states.async_remove(entity_id)

        shutdown_with_agile._kems_alpha723_agile = True
        shadow_module.ShadowValidationRecorder.async_shutdown = shutdown_with_agile

    dashboard = dashboard_module._combined_master_dashboard_bytes
    if not getattr(dashboard, "_kems_alpha723_agile", False):
        original_dashboard = dashboard

        def dashboard_with_agile_shadow() -> bytes:
            content = original_dashboard().decode("utf-8")
            content = _inject_after_cards(content, "control", _AGILE_DASHBOARD_CARDS)
            content = _inject_after_cards(content, "agile", _AGILE_DASHBOARD_CARDS)
            return content.encode("utf-8")

        dashboard_with_agile_shadow._kems_alpha723_agile = True
        dashboard_module._combined_master_dashboard_bytes = dashboard_with_agile_shadow
