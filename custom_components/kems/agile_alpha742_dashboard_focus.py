"""Alpha7.42 focused Agile dashboard telemetry and presentation.

The Full KEMS Agile tab had accumulated implementation, validation and planning
cards over several alpha releases. That information remains available through
KEMS diagnostics, but the primary dashboard now prioritises the operator view:

* live/actual power beside the current Agile digital-twin routing;
* one graph for live power and one graph for the simulated Agile power;
* a compact today table covering house, solar, grid, battery and cost totals;
* only the small set of plan/safety indicators needed to understand the next
  action.

This patch is reporting-only. It does not alter dispatch, reserve, tariff,
forecast, price-horizon or hardware-write behaviour.
"""

from __future__ import annotations

import math
from typing import Any

from . import agile_smart_export_runtime_base as runtime
from .kems_core import SimulationConfig

_LIVE_SUMMARY = "sensor.kems_agile_live_today_summary"
_SIM_POWER_SENSORS = {
    "sensor.kems_agile_simulated_house_load_power": (
        "Full KEMS Agile simulated house load",
        "simulated_house_load_kw",
    ),
    "sensor.kems_agile_simulated_solar_power": (
        "Full KEMS Agile simulated solar power",
        "solar_power_kw",
    ),
    "sensor.kems_agile_simulated_grid_import_power": (
        "Full KEMS Agile simulated grid import",
        "grid_import_kw",
    ),
    "sensor.kems_agile_simulated_grid_export_power": (
        "Full KEMS Agile simulated grid export",
        "grid_export_kw",
    ),
}
_SIM_BATTERY_SENSOR = "sensor.kems_agile_simulated_battery_net_power"
_ALPHA742_SENSOR_IDS = (*_SIM_POWER_SENSORS, _SIM_BATTERY_SENSOR, _LIVE_SUMMARY)

_AGILE_VIEW_START = (
    "  - title: Full KEMS Agile\n"
    "    path: full-kems-agile\n"
    "    icon: mdi:transmission-tower-export\n"
)
_COMPARE_VIEW_START = (
    "  - title: Compare\n"
    "    path: compare\n"
    "    icon: mdi:compare-horizontal\n"
)

_AGILE_FOCUSED_VIEW = r"""  - title: Full KEMS Agile
    path: full-kems-agile
    icon: mdi:transmission-tower-export
    cards:
      - type: markdown
        title: Full KEMS Agile — live vs simulation
        content: |
          **Decision now:** **{{ state_attr('sensor.kems_agile_live_scenario', 'routing_action') or state_attr('sensor.kems_agile_rolling_export_plan', 'dispatch_action') or 'Building plan' }}**  
          **Agile export price now:** {{ states('sensor.kems_agile_export_rate_now') }} p/kWh  
          **Tomorrow prices:** {{ states('sensor.kems_agile_tomorrow_publication_plan') }}  
          **Next planned export slot:** {{ states('sensor.kems_agile_rolling_next_export_slot') }}

          This page keeps the operating view deliberately simple. Detailed price-slot, validation and shadow evidence remains available in KEMS diagnostics.

      - type: grid
        columns: 4
        square: false
        cards:
          - type: tile
            entity: sensor.kems_agile_smart_export_status
            name: Agile status
          - type: tile
            entity: sensor.kems_agile_dispatch_mode
            name: Dispatch mode
          - type: tile
            entity: sensor.kems_agile_battery_export_target_now
            name: Battery export target
          - type: tile
            entity: sensor.kems_agile_simulated_battery_soc_now
            name: Simulated battery SOC

      - type: grid
        columns: 2
        square: false
        cards:
          - type: markdown
            title: Live / actual now
            content: |
              | Power flow | Live |
              |---|---:|
              | House load | **{{ states('sensor.kems_house_load') }} kW** |
              | Solar generation | {{ states('sensor.kems_solar_power') if states('sensor.kems_solar_power') not in ['unknown','unavailable'] else '—' }}{% if states('sensor.kems_solar_power') not in ['unknown','unavailable'] %} kW{% endif %} |
              | Battery power | {{ states('sensor.kems_battery_power') if states('sensor.kems_battery_power') not in ['unknown','unavailable'] else '—' }}{% if states('sensor.kems_battery_power') not in ['unknown','unavailable'] %} kW{% endif %} |
              | Grid import | {{ states('sensor.kems_grid_import') }} kW |
              | Grid export | {{ states('sensor.kems_grid_export') if states('sensor.kems_grid_export') not in ['unknown','unavailable'] else '—' }}{% if states('sensor.kems_grid_export') not in ['unknown','unavailable'] %} kW{% endif %} |

              *A dash means the physical source is not commissioned or unavailable; KEMS does not replace missing live solar/battery data with zero.*
          - type: markdown
            title: Full KEMS Agile simulation now
            content: |
              | Power flow | Simulated |
              |---|---:|
              | House load | **{{ states('sensor.kems_agile_simulated_house_load_power') }} kW** |
              | Solar generation | {{ states('sensor.kems_agile_simulated_solar_power') }} kW |
              | Battery net | {{ states('sensor.kems_agile_simulated_battery_net_power') }} kW |
              | Grid import | {{ states('sensor.kems_agile_simulated_grid_import_power') }} kW |
              | Grid export | {{ states('sensor.kems_agile_simulated_grid_export_power') }} kW |

              *Battery net is positive while discharging and negative while charging.*

      - type: history-graph
        title: Actual power — last 24 hours
        hours_to_show: 24
        entities:
          - entity: sensor.kems_house_load
            name: House load
          - entity: sensor.kems_solar_power
            name: Solar
          - entity: sensor.kems_battery_power
            name: Battery
          - entity: sensor.kems_grid_import
            name: Grid import
          - entity: sensor.kems_grid_export
            name: Grid export

      - type: history-graph
        title: Full KEMS Agile simulated power — last 24 hours
        hours_to_show: 24
        entities:
          - entity: sensor.kems_agile_simulated_house_load_power
            name: House load
          - entity: sensor.kems_agile_simulated_solar_power
            name: Solar
          - entity: sensor.kems_agile_simulated_battery_net_power
            name: Battery (+ discharge / − charge)
          - entity: sensor.kems_agile_simulated_grid_import_power
            name: Grid import
          - entity: sensor.kems_agile_simulated_grid_export_power
            name: Grid export

      - type: markdown
        title: Today totals — actual vs Full KEMS Agile
        content: |
          {% set live = state_attr('sensor.kems_agile_live_today_summary', 'totals') or {} %}
          {% set periods = state_attr('sensor.kems_agile_smart_export_plan', 'periods') or {} %}
          {% set sim = (periods.get('today', {}) or {}).get('agile_smart_export', {}) %}
          {% set sim_house = (sim.get('solar_to_home_kwh', 0)|float) + (sim.get('battery_to_home_kwh', 0)|float) + (sim.get('grid_import_kwh', 0)|float) - (sim.get('grid_to_battery_kwh', 0)|float) %}
          {% set sim_charge = (sim.get('solar_to_battery_kwh', 0)|float) + (sim.get('grid_to_battery_kwh', 0)|float) %}
          {% set sim_discharge = (sim.get('battery_to_home_kwh', 0)|float) + (sim.get('battery_export_kwh', 0)|float) %}
          | Metric | Actual / observed | Agile simulation |
          |---|---:|---:|
          | House energy | {{ states('sensor.kems_whole_home_energy_today') }} kWh | {{ sim_house | round(3) }} kWh |
          | Solar generation | {{ (live.get('solar_generation_kwh') | round(3)) if live.get('solar_generation_kwh') is not none else '—' }}{% if live.get('solar_generation_kwh') is not none %} kWh{% endif %} | {{ sim.get('solar_generation_kwh', 0) | round(3) }} kWh |
          | Grid import | {{ states('sensor.kems_observed_grid_import_today') }} kWh | {{ sim.get('grid_import_kwh', 0) | round(3) }} kWh |
          | Grid export | {{ states('sensor.kems_observed_grid_export_today') }} kWh | {{ sim.get('grid_export_kwh', 0) | round(3) }} kWh |
          | Battery charged | {{ (live.get('battery_charge_kwh') | round(3)) if live.get('battery_charge_kwh') is not none else '—' }}{% if live.get('battery_charge_kwh') is not none %} kWh{% endif %} | {{ sim_charge | round(3) }} kWh |
          | Battery discharged | {{ (live.get('battery_discharge_kwh') | round(3)) if live.get('battery_discharge_kwh') is not none else '—' }}{% if live.get('battery_discharge_kwh') is not none %} kWh{% endif %} | {{ sim_discharge | round(3) }} kWh |
          | Export income | {{ states('sensor.kems_observed_export_income_today') }} p | {{ sim.get('export_income_pence', 0) | round(2) }} p |
          | Net electricity cost | **{{ states('sensor.kems_observed_cost_today') }} p** | **{{ sim.get('economic_net_cost_pence', 0) | round(2) }} p** |

      - type: markdown
        title: Period cost summary
        content: |
          {% set periods = state_attr('sensor.kems_agile_smart_export_plan', 'periods') or {} %}
          | Period | Actual / observed | Full KEMS Agile simulation |
          |---|---:|---:|
          | Today | {{ states('sensor.kems_observed_cost_today') }} p | {{ ((periods.get('today', {}) or {}).get('agile_smart_export', {}) or {}).get('economic_net_cost_pence', '—') }} p |
          | Last 7 days | {{ states('sensor.kems_week_energy_summary') }} p | {{ ((periods.get('7_days', {}) or {}).get('agile_smart_export', {}) or {}).get('economic_net_cost_pence', '—') }} p |
          | Last 30 days | {{ states('sensor.kems_month_energy_summary') }} p | {{ ((periods.get('30_days', {}) or {}).get('agile_smart_export', {}) or {}).get('economic_net_cost_pence', '—') }} p |
          | All tracked | {{ states('sensor.kems_all_time_energy_summary') }} p | {{ ((periods.get('all_time', {}) or {}).get('agile_smart_export', {}) or {}).get('economic_net_cost_pence', '—') }} p |

      - type: grid
        columns: 2
        square: false
        cards:
          - type: entities
            title: Plan now
            show_header_toggle: false
            entities:
              - sensor.kems_agile_export_rate_now
              - sensor.kems_agile_rolling_next_export_slot
              - sensor.kems_agile_rolling_exportable_energy
              - sensor.kems_agile_rolling_protected_house_energy
              - sensor.kems_agile_tomorrow_publication_plan
          - type: entities
            title: Safety / confidence
            show_header_toggle: false
            entities:
              - sensor.kems_agile_price_data_quality
              - sensor.kems_data_quality
              - sensor.kems_learning_confidence
              - sensor.kems_forecast_solar_tomorrow
              - sensor.kems_forecast_house_demand_tomorrow
"""


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integrate_actual_today(self) -> dict[str, Any]:
    """Integrate retained live snapshots without inventing unavailable sources."""
    records = sorted(
        list(getattr(self, "_panel_today_records", []) or []),
        key=lambda item: item.timestamp,
    )
    config = getattr(self, "_rolling_config", None)
    positive_discharge = (
        bool(config.battery_power_positive_is_discharge)
        if isinstance(config, SimulationConfig)
        else True
    )
    totals = {
        "house_energy_kwh": 0.0,
        "solar_generation_kwh": 0.0,
        "grid_import_kwh": 0.0,
        "grid_export_kwh": 0.0,
        "battery_charge_kwh": 0.0,
        "battery_discharge_kwh": 0.0,
    }
    samples = {key: 0 for key in totals}
    intervals = 0

    for current, following in zip(records, records[1:], strict=False):
        hours = min(
            max((following.timestamp - current.timestamp).total_seconds(), 0.0)
            / 3600.0,
            0.5,
        )
        if hours <= 0:
            continue
        intervals += 1
        stale = set(getattr(current, "stale_fields", ()) or ())
        for key, field in (
            ("house_energy_kwh", "house_load_kw"),
            ("solar_generation_kwh", "solar_power_kw"),
            ("grid_import_kwh", "grid_import_kw"),
            ("grid_export_kwh", "grid_export_kw"),
        ):
            if field in stale:
                continue
            value = _number(getattr(current, field, None))
            if value is None:
                continue
            totals[key] += max(value, 0.0) * hours
            samples[key] += 1

        if "battery_power_kw" in stale:
            continue
        battery = _number(getattr(current, "battery_power_kw", None))
        if battery is None:
            continue
        normalised = battery if positive_discharge else -battery
        if normalised >= 0:
            totals["battery_discharge_kwh"] += normalised * hours
            samples["battery_discharge_kwh"] += 1
        else:
            totals["battery_charge_kwh"] += abs(normalised) * hours
            samples["battery_charge_kwh"] += 1

    result: dict[str, float | None] = {}
    coverage: dict[str, float] = {}
    for key, total in totals.items():
        result[key] = round(total, 3) if samples[key] else None
        coverage[key] = round(samples[key] / intervals, 4) if intervals else 0.0
    return {
        "available": bool(intervals),
        "intervals": intervals,
        "totals": result,
        "coverage": coverage,
        "battery_power_positive_means_discharge": positive_discharge,
        "missing_sources_remain_unavailable": True,
        "reporting_only": True,
        "hardware_writes": "blocked",
    }


def _publish_power_sensor(
    self,
    entity_id: str,
    friendly_name: str,
    value: Any,
    *,
    reason: str | None = None,
) -> None:
    """Publish one recorder-friendly power sensor."""
    number = _number(value)
    self._set(
        entity_id,
        round(number, 3) if number is not None else "unavailable",
        {
            "friendly_name": friendly_name,
            "unit_of_measurement": "kW",
            "device_class": "power",
            "state_class": "measurement",
            "reason": reason,
            "source": "Full KEMS Agile current coordinator digital twin",
            "reporting_only": True,
            "hardware_writes": "blocked",
        },
    )


def _publish_with_alpha742(self, state: dict[str, Any]) -> None:
    """Publish focused graph telemetry after the complete Alpha7.41 chain."""
    alpha742_original_publish(self, state)
    snapshot = state.get("current_routing_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    reason = str(snapshot.get("reason") or "current Agile routing unavailable")

    for entity_id, (friendly_name, key) in _SIM_POWER_SENSORS.items():
        _publish_power_sensor(
            self,
            entity_id,
            friendly_name,
            snapshot.get(key) if snapshot.get("available") else None,
            reason=None if snapshot.get("available") else reason,
        )

    battery_net = None
    if snapshot.get("available"):
        discharge = _number(snapshot.get("total_discharge_kw")) or 0.0
        charge = (_number(snapshot.get("solar_to_battery_kw")) or 0.0) + (
            _number(snapshot.get("grid_to_battery_kw")) or 0.0
        )
        battery_net = discharge - charge
    _publish_power_sensor(
        self,
        _SIM_BATTERY_SENSOR,
        "Full KEMS Agile simulated battery net power",
        battery_net,
        reason=None if snapshot.get("available") else reason,
    )

    live = _integrate_actual_today(self)
    self._set(
        _LIVE_SUMMARY,
        "Ready" if live.get("available") else "Waiting for live history",
        {
            "friendly_name": "Full KEMS Agile live today summary",
            **live,
        },
    )


def improve_alpha742_dashboard(content: str) -> str:
    """Replace the accumulated Agile tab with the focused operator view."""
    start = content.find(_AGILE_VIEW_START)
    if start < 0:
        raise ValueError("Alpha7.42 Full KEMS Agile dashboard marker missing")
    end = content.find(_COMPARE_VIEW_START, start + len(_AGILE_VIEW_START))
    if end < 0:
        raise ValueError("Alpha7.42 Compare dashboard marker missing")
    return content[:start] + _AGILE_FOCUSED_VIEW.rstrip() + "\n\n" + content[end:]


def install_alpha742_dashboard_focus_patch() -> None:
    """Install focused telemetry/dashboard after Alpha7.41."""
    global alpha742_original_publish
    global alpha742_original_shutdown

    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_alpha742_dashboard_focus", False):
        alpha742_original_publish = publish
        _publish_with_alpha742._kems_alpha742_dashboard_focus = True
        runtime.EfficientAgileSmartExportManager._publish = _publish_with_alpha742

    shutdown = runtime.EfficientAgileSmartExportManager.async_shutdown
    if not getattr(shutdown, "_kems_alpha742_dashboard_focus", False):
        alpha742_original_shutdown = shutdown

        async def shutdown_with_alpha742(self) -> None:
            await alpha742_original_shutdown(self)
            for entity_id in _ALPHA742_SENSOR_IDS:
                self._hass.states.async_remove(entity_id)

        shutdown_with_alpha742._kems_alpha742_dashboard_focus = True
        runtime.EfficientAgileSmartExportManager.async_shutdown = shutdown_with_alpha742

    from . import dashboard as dashboard_module

    original_dashboard = dashboard_module._combined_master_dashboard_bytes
    if getattr(original_dashboard, "_kems_alpha742_dashboard_focus", False):
        return

    def combined_alpha742_dashboard() -> bytes:
        return improve_alpha742_dashboard(original_dashboard().decode("utf-8")).encode(
            "utf-8"
        )

    combined_alpha742_dashboard._kems_alpha742_dashboard_focus = True
    dashboard_module._combined_master_dashboard_bytes = combined_alpha742_dashboard
