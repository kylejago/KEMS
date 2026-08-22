"""Live Agile Smart Export scenario reporting and dashboard view."""

# ruff: noqa: E501

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import agile_smart_export as agile_base
from . import agile_smart_export_runtime_base as runtime
from . import dashboard as dashboard_module

_LIVE_SENSOR = "sensor.kems_agile_live_scenario"
_SIMULATED_SOC_SENSOR = "sensor.kems_agile_simulated_battery_soc_now"
_PLANNED_SOC_SENSOR = "sensor.kems_agile_planned_battery_soc_now"
_REQUIRED_ROUTING_FIELDS = (
    "house_load_kwh",
    "solar_generation_kwh",
    "grid_import_kwh",
    "grid_export_kwh",
    "solar_to_home_kwh",
    "solar_to_battery_kwh",
    "solar_export_kwh",
    "grid_to_battery_kwh",
    "battery_to_home_kwh",
    "battery_export_kwh",
    "ending_soc_percent",
)

_AGILE_LIVE_VIEW = r"""
  - title: Agile Smart Export
    path: agile-smart-export
    icon: mdi:transmission-tower-export
    cards:
      - type: markdown
        content: |
          # Agile Smart Export — Live Scenario
          This is the live **simulation-only** view of the Agile Smart Export strategy. It uses the same battery, inverter, reserve, solar, house-load and import-safety constraints as the comparison engine, but optimises export timing against the real Region L Agile Outgoing half-hour prices.

          **Status:** **{{ states('sensor.kems_agile_smart_export_status') }}**  
          **Current action:** {{ states('sensor.kems_agile_smart_export_plan') }}  
          **Current Agile rate:** {{ states('sensor.kems_agile_export_rate_now') }} p/kWh  
          **Routing basis:** {{ state_attr('sensor.kems_agile_live_scenario', 'routing_basis') or 'Waiting for simulated routing' }}  
          **Routing slot:** {{ state_attr('sensor.kems_agile_live_scenario', 'routing_slot') or '—' }}

          The live decision and Agile rate are current. When the active half-hour has not yet produced a complete replay interval, the routing table below uses the latest completed simulated half-hour and labels that basis explicitly rather than inventing live power flows.

      - type: grid
        columns: 4
        square: false
        cards:
          - type: tile
            entity: sensor.kems_agile_smart_export_status
            name: Smart Export status
          - type: tile
            entity: sensor.kems_agile_export_rate_now
            name: Region L rate now
          - type: tile
            entity: sensor.kems_agile_smart_export_plan
            name: Current action
          - type: tile
            entity: sensor.kems_agile_simulated_battery_soc_now
            name: Agile simulated SOC now

      - type: grid
        columns: 4
        square: false
        cards:
          - type: tile
            entity: sensor.kems_battery_state_of_charge
            name: Live hardware battery SOC
          - type: tile
            entity: sensor.kems_agile_smart_export_cost_today
            name: Agile net cost today
          - type: tile
            entity: sensor.kems_agile_smart_export_export_income_today
            name: Agile export income today
          - type: tile
            entity: sensor.kems_agile_advantage_today
            name: Advantage vs Full KEMS

      - type: markdown
        title: Current Agile Smart Export power routing
        content: |
          {% set e = 'sensor.kems_agile_live_scenario' %}
          | Flow | Simulated power |
          |---|---:|
          | House demand | {{ state_attr(e, 'current_house_load_kw') if state_attr(e, 'current_house_load_kw') is not none else '—' }} kW |
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

          **Current decision:** {{ state_attr(e, 'current_action') or states('sensor.kems_agile_smart_export_plan') }}  
          **Routing action:** {{ state_attr(e, 'routing_action') or '—' }}  
          **Current Agile rate:** {{ state_attr(e, 'current_agile_rate_pence') if state_attr(e, 'current_agile_rate_pence') is not none else states('sensor.kems_agile_export_rate_now') }} p/kWh  
          **Routing basis:** {{ state_attr(e, 'routing_basis') or '—' }}  
          **Routing slot:** {{ state_attr(e, 'routing_slot') or '—' }}

      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: Scenario totals today
            show_header_toggle: false
            entities:
              - entity: sensor.kems_agile_solar_to_home_today
                name: Solar → home
              - entity: sensor.kems_agile_smart_export_export_income_today
                name: Export income
              - entity: sensor.kems_agile_smart_export_weighted_rate_today
                name: Weighted achieved rate
              - entity: sensor.kems_agile_advantage_today
                name: Advantage vs Full KEMS Forecast
          - type: entities
            title: Battery and price state
            show_header_toggle: false
            entities:
              - entity: sensor.kems_agile_simulated_battery_soc_now
                name: Agile simulated SOC now
              - entity: sensor.kems_battery_state_of_charge
                name: Live hardware SOC
              - entity: sensor.kems_agile_export_rate_now
                name: Current Region L rate
              - entity: sensor.kems_agile_price_data_quality
                name: Agile price coverage

      - type: history-graph
        title: Agile scenario economics — 24 hours
        hours_to_show: 24
        entities:
          - entity: sensor.kems_agile_smart_export_cost_today
            name: Agile net cost
          - entity: sensor.kems_agile_smart_export_export_income_today
            name: Agile export income
          - entity: sensor.kems_agile_advantage_today
            name: Advantage vs Full KEMS

      - type: history-graph
        title: Agile battery SOC — 24 hours
        hours_to_show: 24
        entities:
          - entity: sensor.kems_agile_simulated_battery_soc_now
            name: Agile simulated SOC
          - entity: sensor.kems_battery_state_of_charge
            name: Live hardware SOC

      - type: markdown
        title: Current and upcoming Agile plan
        content: |
          {% set slots = state_attr('sensor.kems_agile_smart_export_plan', 'today_slots') or [] %}
          {% set now = as_timestamp(now()) %}
          | Time | Agile p/kWh | Action | Solar → home | Solar → battery | Grid export | Battery export | End SOC |
          |---|---:|---|---:|---:|---:|---:|---:|
          {% set ns = namespace(count=0) %}
          {% for p in slots %}
          {% if ns.count < 10 and as_timestamp(p.get('valid_to')) >= now %}
          | {{ p.get('label', '') }} | {{ '%.2f'|format(p.get('rate_pence', 0)|float) }} | {{ (p.get('actions') or ['future slot'])|join(', ') }} | {{ p.get('solar_to_home_kwh') if p.get('solar_to_home_kwh') is not none else '—' }} | {{ p.get('solar_to_battery_kwh') if p.get('solar_to_battery_kwh') is not none else '—' }} | {{ p.get('grid_export_kwh') if p.get('grid_export_kwh') is not none else '—' }} | {{ p.get('battery_export_kwh') if p.get('battery_export_kwh') is not none else '—' }} | {{ (p.get('ending_soc_percent') ~ '%') if p.get('ending_soc_percent') is not none else '—' }} |
          {% set ns.count = ns.count + 1 %}
          {% endif %}
          {% endfor %}
"""


def _number(value: Any) -> float | None:
    """Return a float for one simulation value when available."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _agile_simulated_soc_now(state: dict[str, Any]) -> float | None:
    """Return the latest replay SOC for today's Agile strategy."""
    periods = state.get("periods")
    if not isinstance(periods, dict):
        return None
    today = periods.get("today")
    if not isinstance(today, dict):
        return None
    agile = today.get("agile_smart_export")
    if not isinstance(agile, dict):
        return None
    return _number(agile.get("ending_soc_percent"))


def _slot_bounds(slot: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Parse one Agile slot's UTC bounds."""
    try:
        start = datetime.fromisoformat(str(slot["valid_from"])).astimezone(UTC)
        end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
    except (KeyError, TypeError, ValueError):
        return None
    return start, end


def _routing_slot(state: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Prefer the current complete slot, otherwise the latest completed slot."""
    generated_at = state.get("generated_at")
    try:
        now = datetime.fromisoformat(str(generated_at)).astimezone(UTC)
    except (TypeError, ValueError):
        return None, "unavailable"

    latest: tuple[datetime, dict[str, Any]] | None = None
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        bounds = _slot_bounds(slot)
        if bounds is None:
            continue
        start, end = bounds
        complete = all(slot.get(key) is not None for key in _REQUIRED_ROUTING_FIELDS)
        if not complete:
            continue
        if start <= now < end:
            return slot, "current simulated half-hour"
        if end <= now and (latest is None or end > latest[0]):
            latest = (end, slot)
    if latest is None:
        return None, "waiting for first complete simulated half-hour"
    return latest[1], "latest completed simulated half-hour"


def _routing_attributes(state: dict[str, Any]) -> dict[str, Any]:
    """Build Full-KEMS-style power attributes from a complete Agile slot."""
    slot, basis = _routing_slot(state)
    attrs: dict[str, Any] = {
        "available": slot is not None,
        "routing_basis": basis,
        "current_action": state.get("current_action"),
        "current_agile_rate_pence": _number(state.get("current_rate_pence")),
        "simulated_battery_soc_percent": _agile_simulated_soc_now(state),
    }
    if slot is None:
        return attrs

    bounds = _slot_bounds(slot)
    if bounds is None:
        return attrs
    start, end = bounds
    hours = max((end - start).total_seconds() / 3600.0, 0.0)
    if hours <= 0:
        return attrs

    def power(name: str) -> float | None:
        value = _number(slot.get(name))
        return None if value is None else round(max(value / hours, 0.0), 3)

    attrs.update(
        {
            "routing_slot": slot.get("label"),
            "routing_valid_from": slot.get("valid_from"),
            "routing_valid_to": slot.get("valid_to"),
            "routing_action": ", ".join(slot.get("actions") or ["Hold"]),
            "routing_agile_rate_pence": _number(slot.get("rate_pence")),
            "current_house_load_kw": power("house_load_kwh"),
            "current_solar_power_kw": power("solar_generation_kwh"),
            "current_grid_import_kw": power("grid_import_kwh"),
            "current_grid_export_kw": power("grid_export_kwh"),
            "current_solar_to_home_kw": power("solar_to_home_kwh"),
            "current_solar_to_battery_kw": power("solar_to_battery_kwh"),
            "current_solar_export_kw": power("solar_export_kwh"),
            "current_grid_to_battery_kw": power("grid_to_battery_kwh"),
            "current_battery_to_home_kw": power("battery_to_home_kwh"),
            "current_battery_export_kw": power("battery_export_kwh"),
            "routing_ending_soc_percent": _number(slot.get("ending_soc_percent")),
        }
    )
    return attrs


def install_live_scenario_patch() -> None:
    """Install the live scenario entities and dashboard view exactly once."""
    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_agile_live_scenario", False):
        original_publish = publish

        def publish_with_live_scenario(self, state: dict[str, Any]) -> None:
            original_publish(self, state)
            soc = _agile_simulated_soc_now(state)
            self._set(
                _SIMULATED_SOC_SENSOR,
                agile_base._state(soc),
                {
                    "friendly_name": "Agile Smart Export simulated battery SOC now",
                    "unit_of_measurement": "%",
                    "mode": "simulation_only",
                    "available": soc is not None,
                    "meaning": "latest battery SOC reached by today's Agile replay",
                },
            )

            planned = self._hass.states.get(_PLANNED_SOC_SENSOR)
            if planned is None or str(planned.state).strip().lower() in {
                "unknown",
                "unavailable",
                "none",
            }:
                self._set(
                    _PLANNED_SOC_SENSOR,
                    agile_base._state(soc),
                    {
                        "friendly_name": "Agile Smart Export simulated battery SOC now",
                        "unit_of_measurement": "%",
                        "mode": "simulation_only",
                        "available": soc is not None,
                        "basis": "latest Agile replay point",
                        "meaning": (
                            "current simulated SOC; used when the active half-hour "
                            "has not yet settled enough data for an end-slot SOC"
                        ),
                    },
                )

            attrs = _routing_attributes(state)
            self._set(
                _LIVE_SENSOR,
                "Ready" if state.get("ready") else "Waiting for complete data",
                {
                    "friendly_name": "Agile Smart Export live scenario",
                    "mode": "simulation_only",
                    **attrs,
                },
            )

        publish_with_live_scenario._kems_agile_live_scenario = True
        runtime.EfficientAgileSmartExportManager._publish = publish_with_live_scenario

    original_dashboard = dashboard_module._combined_master_dashboard_bytes
    if not getattr(original_dashboard, "_kems_agile_live_scenario", False):

        def combined_dashboard_with_live_scenario() -> bytes:
            content = original_dashboard().decode("utf-8")
            content = content.replace(
                "            name: Live battery SOC\n",
                "            name: Live hardware battery SOC\n",
            )
            content = content.replace(
                "            name: Agile planned SOC — end of current slot\n",
                "            name: Agile simulated SOC now\n",
            )
            if "    path: agile-smart-export\n" not in content:
                content = f"{content.rstrip()}\n\n{_AGILE_LIVE_VIEW.lstrip()}"
            return content.encode()

        combined_dashboard_with_live_scenario._kems_agile_live_scenario = True
        dashboard_module._combined_master_dashboard_bytes = (
            combined_dashboard_with_live_scenario
        )
