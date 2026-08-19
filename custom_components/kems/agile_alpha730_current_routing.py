"""Alpha 7.30 coherent current-routing snapshot for Agile Smart Export.

Alpha7.29 corrected the primary house-demand label, but the rest of the Agile
routing card could still mix a fresh price/house reading with elapsed-slot
attributes from an older half-hour. At a settlement boundary those elapsed
attributes may also be unavailable, producing misleading dashes and stale
routing labels.

Alpha7.30 rebuilds the display snapshot from one current coordinator scan. It
uses the same proposal simulation engine for the digital-twin AC routing and
then substitutes the exact current Agile rolling battery candidate, matching
the Alpha7.24 shadow-outcome accounting model. This module is reporting-only:
it does not alter the optimiser, rolling plan, command candidate, safety
validator, SOC policy, price-horizon policy, or hardware-write boundary.
"""

# ruff: noqa: E501

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_smart_export_runtime_base as runtime
from . import dashboard as dashboard_module
from .kems_core import SimulationConfig, SimulationEngine

_LIVE_SENSOR = "sensor.kems_agile_live_scenario"
_HOUSE_SENSOR = "sensor.kems_house_load"
_EPSILON = 1e-6


_CURRENT_ROUTING_CARD = r"""        title: Current Agile Smart Export power routing
        content: |
          {% set e = 'sensor.kems_agile_live_scenario' %}
          | Flow | Current power |
          |---|---:|
          | House demand (live) | {{ states('sensor.kems_house_load') }} kW |
          | Digital-twin house demand | {{ state_attr(e, 'simulated_house_load_kw') if state_attr(e, 'simulated_house_load_kw') is not none else '—' }} kW |
          | Solar generation | {{ state_attr(e, 'current_solar_power_kw') if state_attr(e, 'current_solar_power_kw') is not none else '—' }} kW |
          | Grid import | {{ state_attr(e, 'current_grid_import_kw') if state_attr(e, 'current_grid_import_kw') is not none else '—' }} kW |
          | Grid export | {{ state_attr(e, 'current_grid_export_kw') if state_attr(e, 'current_grid_export_kw') is not none else '—' }} kW |
          | Solar → home | {{ state_attr(e, 'current_solar_to_home_kw') if state_attr(e, 'current_solar_to_home_kw') is not none else '—' }} kW |
          | Solar → battery | {{ state_attr(e, 'current_solar_to_battery_kw') if state_attr(e, 'current_solar_to_battery_kw') is not none else '—' }} kW |
          | Solar → export | {{ state_attr(e, 'current_solar_export_kw') if state_attr(e, 'current_solar_export_kw') is not none else '—' }} kW |
          | Grid → battery | {{ state_attr(e, 'current_grid_to_battery_kw') if state_attr(e, 'current_grid_to_battery_kw') is not none else '—' }} kW |
          | Battery → home | {{ state_attr(e, 'current_battery_to_home_kw') if state_attr(e, 'current_battery_to_home_kw') is not none else '—' }} kW |
          | Battery → export | {{ state_attr(e, 'current_battery_export_kw') if state_attr(e, 'current_battery_export_kw') is not none else '—' }} kW |
          | Agile simulated SOC now | {{ states('sensor.kems_agile_simulated_battery_soc_now') }}% |

          **Power basis:** one current KEMS coordinator routing snapshot. The proposal digital twin supplies current solar/routing context and the exact Agile rolling battery candidate is substituted before grid/export totals are shown.  
          **Current decision:** {{ state_attr(e, 'routing_action') or '—' }}  
          **Current Agile rate:** {{ state_attr(e, 'current_agile_rate_pence') if state_attr(e, 'current_agile_rate_pence') is not none else states('sensor.kems_agile_export_rate_now') }} p/kWh  
          **Routing basis:** {{ state_attr(e, 'routing_basis') or '—' }}  
          **Routing slot:** {{ state_attr(e, 'routing_slot') or '—' }}

          **House-demand basis:** `sensor.kems_house_load` is the live value shown on the Live tab. The digital-twin house value and the previous elapsed-slot evidence remain diagnostic attributes, but they no longer drive this current-routing table.
"""


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _current_slot(state: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """Return the actual current Agile settlement slot for this scan."""
    now_utc = now.astimezone(UTC)
    slots = state.get("today_slots")
    if not isinstance(slots, list):
        return None
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        try:
            start = datetime.fromisoformat(str(slot["valid_from"])).astimezone(UTC)
            end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
        except (KeyError, TypeError, ValueError):
            continue
        if start <= now_utc < end:
            return slot
    return None


def _current_simulation(self, now: datetime):
    """Rebuild the current proposal simulation from this scan's Agile records."""
    records = list(getattr(self, "_panel_today_records", []) or [])
    config = getattr(self, "_rolling_config", None)
    if not records or not isinstance(config, SimulationConfig):
        return None, None, None

    current = records[-1]
    predicted_house = _number(getattr(self, "_rolling_predicted_house_kwh", None))
    simulation = SimulationEngine().simulate_today(
        records,
        now,
        config,
        predicted_house,
        current_snapshot=current,
    )
    return current, config, simulation


def _snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
    """Build one coherent current routing snapshot without changing dispatch."""
    now = getattr(self, "_rolling_now", None)
    if not isinstance(now, datetime):
        try:
            now = datetime.fromisoformat(str(state.get("generated_at")))
        except (TypeError, ValueError):
            return {
                "available": False,
                "reason": "current coordinator timestamp unavailable",
                "reporting_only": True,
            }

    current, config, simulation = _current_simulation(self, now)
    plan = state.get("rolling_export_plan")
    plan = plan if isinstance(plan, dict) else {}
    slot = _current_slot(state, now)

    if current is None or config is None or simulation is None:
        return {
            "available": False,
            "reason": "current proposal simulation unavailable",
            "generated_at": now.isoformat(),
            "routing_slot": slot.get("label") if isinstance(slot, dict) else None,
            "routing_action": plan.get("dispatch_action"),
            "reporting_only": True,
        }

    house = _number(simulation.current_simulated_house_load_kw)
    solar = _number(simulation.current_simulated_solar_power_kw)
    solar_to_battery = _number(
        simulation.current_simulated_solar_to_battery_power_kw
    )
    base_battery_home = _number(simulation.current_simulated_battery_to_home_power_kw)
    base_battery_export = _number(simulation.current_simulated_battery_export_power_kw)
    base_ac_output = _number(simulation.current_simulated_total_kh7_output_kw)
    grid_bypass = _number(simulation.current_simulated_grid_bypass_power_kw)
    battery_charge = _number(simulation.current_simulated_battery_charge_power_kw)

    if house is None or solar is None:
        return {
            "available": False,
            "reason": "current digital-twin house/solar power unavailable",
            "generated_at": now.isoformat(),
            "routing_slot": slot.get("label") if isinstance(slot, dict) else None,
            "routing_action": plan.get("dispatch_action"),
            "reporting_only": True,
        }

    house = max(house, 0.0)
    solar = max(solar, 0.0)
    solar_to_battery = max(solar_to_battery or 0.0, 0.0)
    base_battery_home = max(base_battery_home or 0.0, 0.0)
    base_battery_export = max(base_battery_export or 0.0, 0.0)
    grid_bypass = max(grid_bypass or 0.0, 0.0)
    battery_charge = max(battery_charge or 0.0, 0.0)

    candidate_home = _number(plan.get("current_house_battery_kw"))
    candidate_export = _number(plan.get("current_battery_export_target_kw"))
    candidate_discharge = _number(plan.get("current_battery_discharge_target_kw"))
    if candidate_home is None:
        candidate_home = base_battery_home
    if candidate_export is None:
        candidate_export = base_battery_export
    candidate_home = max(candidate_home, 0.0)
    candidate_export = max(candidate_export, 0.0)
    if candidate_discharge is None:
        candidate_discharge = candidate_home + candidate_export
    candidate_discharge = max(candidate_discharge, 0.0)

    # The proposal simulation already contains the current routed AC result.
    # Recover its solar-to-home/export split, then substitute only the Agile
    # battery candidate exactly as Alpha7.24 does for shadow outcome parity.
    solar_ac_available = max(solar - solar_to_battery, 0.0)
    base_solar_to_home = min(
        max(house - grid_bypass - base_battery_home, 0.0),
        solar_ac_available,
    )
    base_solar_export = 0.0
    if base_ac_output is not None:
        base_solar_export = max(
            base_ac_output
            - base_battery_home
            - base_battery_export
            - base_solar_to_home,
            0.0,
        )
    base_solar_export = min(
        base_solar_export,
        max(solar_ac_available - base_solar_to_home, 0.0),
    )

    grid_to_battery = max(battery_charge - solar_to_battery, 0.0)
    grid_import = max(house - base_solar_to_home - candidate_home, 0.0)
    grid_import += grid_to_battery
    grid_export = base_solar_export + candidate_export
    normalised_ac_output = (
        max(
            (base_ac_output or (base_solar_to_home + base_solar_export))
            - base_battery_home
            - base_battery_export
            + candidate_discharge,
            0.0,
        )
    )

    current_rate = (
        _number(slot.get("rate_pence"))
        if isinstance(slot, dict)
        else _number(state.get("current_rate_pence"))
    )
    live_house = _number(getattr(current, "house_load_kw", None))
    if live_house is None:
        live_house = house

    return {
        "available": True,
        "version": "0.7.0-alpha7.30",
        "generated_at": now.isoformat(),
        "routing_basis": "current coordinator routing snapshot",
        "routing_slot": slot.get("label") if isinstance(slot, dict) else None,
        "routing_valid_from": (
            slot.get("valid_from") if isinstance(slot, dict) else None
        ),
        "routing_valid_to": slot.get("valid_to") if isinstance(slot, dict) else None,
        "routing_action": (
            plan.get("dispatch_action")
            or state.get("current_action")
            or "Follow current Agile rolling plan"
        ),
        "dispatch_mode": plan.get("dispatch_mode"),
        "current_agile_rate_pence": current_rate,
        "live_house_load_kw": round(max(live_house, 0.0), 3),
        "simulated_house_load_kw": round(house, 3),
        "solar_power_kw": round(solar, 3),
        "grid_import_kw": round(max(grid_import, 0.0), 3),
        "grid_export_kw": round(max(grid_export, 0.0), 3),
        "solar_to_home_kw": round(max(base_solar_to_home, 0.0), 3),
        "solar_to_battery_kw": round(max(solar_to_battery, 0.0), 3),
        "solar_export_kw": round(max(base_solar_export, 0.0), 3),
        "grid_to_battery_kw": round(max(grid_to_battery, 0.0), 3),
        "battery_to_home_kw": round(max(candidate_home, 0.0), 3),
        "battery_export_kw": round(max(candidate_export, 0.0), 3),
        "total_discharge_kw": round(max(candidate_discharge, 0.0), 3),
        "normalised_kh7_ac_output_kw": round(max(normalised_ac_output, 0.0), 3),
        "simulated_soc_percent": plan.get("simulated_soc_percent"),
        "battery_candidate_basis": "exact current Agile rolling target",
        "solar_routing_basis": "current proposal digital-twin routed AC",
        "reporting_only": True,
        "hardware_writes": "blocked",
    }


def _publish_with_current_routing(self, state: dict[str, Any]) -> None:
    """Publish one final coherent routing snapshot after all prior patches."""
    alpha730_original_publish(self, state)

    snapshot = _snapshot(self, state)
    state["current_routing_snapshot"] = snapshot

    live_state = self._hass.states.get(_LIVE_SENSOR)
    attrs = dict(live_state.attributes) if live_state is not None else {}
    attrs["elapsed_slot_average_evidence"] = {
        "routing_basis": attrs.get("simulated_house_load_basis")
        or attrs.get("routing_basis"),
        "house_load_kw": attrs.get("simulated_house_load_kw"),
        "solar_power_kw": attrs.get("current_solar_power_kw"),
        "grid_import_kw": attrs.get("current_grid_import_kw"),
        "grid_export_kw": attrs.get("current_grid_export_kw"),
        "solar_to_home_kw": attrs.get("current_solar_to_home_kw"),
        "solar_to_battery_kw": attrs.get("current_solar_to_battery_kw"),
        "solar_export_kw": attrs.get("current_solar_export_kw"),
        "grid_to_battery_kw": attrs.get("current_grid_to_battery_kw"),
        "battery_to_home_kw": attrs.get("current_battery_to_home_kw"),
        "battery_export_kw": attrs.get("current_battery_export_kw"),
    }

    if snapshot.get("available"):
        attrs.update(
            {
                "current_house_load_kw": snapshot.get("live_house_load_kw"),
                "live_house_load_kw": snapshot.get("live_house_load_kw"),
                "live_house_load_source": _HOUSE_SENSOR,
                "simulated_house_load_kw": snapshot.get("simulated_house_load_kw"),
                "simulated_house_load_basis": "current coordinator digital twin",
                "current_solar_power_kw": snapshot.get("solar_power_kw"),
                "current_grid_import_kw": snapshot.get("grid_import_kw"),
                "current_grid_export_kw": snapshot.get("grid_export_kw"),
                "current_solar_to_home_kw": snapshot.get("solar_to_home_kw"),
                "current_solar_to_battery_kw": snapshot.get("solar_to_battery_kw"),
                "current_solar_export_kw": snapshot.get("solar_export_kw"),
                "current_grid_to_battery_kw": snapshot.get("grid_to_battery_kw"),
                "current_battery_to_home_kw": snapshot.get("battery_to_home_kw"),
                "current_battery_export_kw": snapshot.get("battery_export_kw"),
                "battery_discharge_target_kw": snapshot.get("total_discharge_kw"),
                "battery_export_target_kw": snapshot.get("battery_export_kw"),
                "routing_basis": snapshot.get("routing_basis"),
                "routing_slot": snapshot.get("routing_slot"),
                "routing_valid_from": snapshot.get("routing_valid_from"),
                "routing_valid_to": snapshot.get("routing_valid_to"),
                "routing_action": snapshot.get("routing_action"),
                "current_action": snapshot.get("routing_action"),
                "dispatch_mode": snapshot.get("dispatch_mode"),
                "current_agile_rate_pence": snapshot.get(
                    "current_agile_rate_pence"
                ),
                "current_routing_snapshot": snapshot,
            }
        )

        live = snapshot.get("live_house_load_kw")
        simulated = snapshot.get("simulated_house_load_kw")
        state["live_house_load_parity"] = {
            "available": live is not None and simulated is not None,
            "source_entity": _HOUSE_SENSOR,
            "live_house_load_kw": live,
            "simulated_house_load_kw": simulated,
            "simulated_house_load_basis": "current coordinator digital twin",
            "difference_kw": (
                round(float(live) - float(simulated), 3)
                if live is not None and simulated is not None
                else None
            ),
            "display_basis": "live KEMS house load",
            "last_updated": snapshot.get("generated_at"),
            "reporting_only": True,
        }

    self._set(
        _LIVE_SENSOR,
        live_state.state if live_state is not None else "Ready",
        attrs,
    )


def _patch_current_routing_card(content: str) -> str:
    """Replace the accumulated legacy card with the current-snapshot card."""
    marker = "        title: Current Agile Smart Export power routing\n"
    start = content.find(marker)
    if start < 0:
        return content
    end = content.find("\n      - type:", start + len(marker))
    if end < 0:
        end = len(content)
    return content[:start] + _CURRENT_ROUTING_CARD.rstrip() + content[end:]


def install_alpha730_current_routing_patch() -> None:
    """Install current-scan routing parity exactly once."""
    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_alpha730_current_routing", False):
        global alpha730_original_publish
        alpha730_original_publish = publish
        _publish_with_current_routing._kems_alpha730_current_routing = True
        runtime.EfficientAgileSmartExportManager._publish = _publish_with_current_routing

    original_dashboard = dashboard_module._combined_master_dashboard_bytes
    if getattr(original_dashboard, "_kems_alpha730_current_routing", False):
        return

    def combined_dashboard_with_alpha730() -> bytes:
        content = original_dashboard().decode("utf-8")
        return _patch_current_routing_card(content).encode("utf-8")

    combined_dashboard_with_alpha730._kems_alpha730_current_routing = True
    dashboard_module._combined_master_dashboard_bytes = combined_dashboard_with_alpha730
