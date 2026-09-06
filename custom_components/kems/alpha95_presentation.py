"""Alpha9.5 customer presentation repair, hardened through Alpha9.10.

Keep current-day dashboard totals on the stable flat KEMS entities and restore the
HA-side Full KEMS Agile panel flow publisher.  This module is reporting-only: it
does not alter optimisation, control eligibility, FoxESS commissioning, or any
hardware-write boundary.
"""

# ruff: noqa: E501

from __future__ import annotations

import math
from typing import Any

from . import agile_panel_presentation_runtime as panel_runtime
from . import agile_smart_export_runtime_base as agile_runtime

_SIMULATED_SOC_ENTITY = "sensor.kems_simulated_battery_state_of_charge"

_LIVE_DAILY_OLD = """              {% set p = ((state_attr('sensor.kems_energy_cost_comparison', 'periods') or {}).get('today', {}) or {}) %}
              {% set live = p.get('live_data', {}) or {} %}
              | Cost | Live Data |
              |---|---:|
              | Electricity import | {{ ('£%.2f' | format((live.get('electricity_import_cost_pence') | float) / 100)) if live.get('electricity_import_cost_pence') is not none else '—' }} |
              | Standing charge | {{ ('£%.2f' | format((live.get('electricity_standing_charge_pence') | float) / 100)) if live.get('electricity_standing_charge_pence') is not none else '—' }} |
              | Export income | {{ ('−£%.2f' | format((live.get('electricity_export_income_pence') | float) / 100)) if live.get('electricity_export_income_pence') is not none else '—' }} |
              | **Electricity total** | **{{ ('£%.2f' | format((live.get('electricity_total_cost_pence') | float) / 100)) if live.get('electricity_total_cost_pence') is not none else '—' }}** |
              | Gas | {{ ('£%.2f' | format((live.get('gas_total_cost_pence') | float) / 100)) if live.get('gas_total_cost_pence') is not none else '—' }} |
              | **TOTAL ENERGY COST** | **{{ ('£%.2f' | format((live.get('total_energy_cost_pence') | float) / 100)) if live.get('total_energy_cost_pence') is not none else '—' }}** |"""

_LIVE_DAILY_NEW = """              {% set net = states('sensor.kems_observed_cost_today') | float(0) %}
              {% set gas = states('sensor.kems_gas_cost_today') | float(0) %}
              {% set total = states('sensor.kems_whole_home_observed_cost_today') | float(net + gas) %}
              {% set export = states('sensor.kems_observed_export_income_today') | float(0) %}
              {% set standing = [total - gas - net, 0] | max %}
              | Cost | Live Data |
              |---|---:|
              | Electricity net before standing | £{{ '%.2f' | format(net / 100) }} |
              | Standing charge | £{{ '%.2f' | format(standing / 100) }} |
              | Export income | −£{{ '%.2f' | format(export / 100) }} |
              | **Electricity total** | **£{{ '%.2f' | format((total - gas) / 100) }}** |
              | Gas | £{{ '%.2f' | format(gas / 100) }} |
              | **TOTAL ENERGY COST** | **£{{ '%.2f' | format(total / 100) }}** |"""

_KEMS_DAILY_OLD = """              {% set p = ((state_attr('sensor.kems_energy_cost_comparison', 'periods') or {}).get('today', {}) or {}) %}
              {% set kems = p.get('kems', {}) or {} %}
              | Cost | KEMS |
              |---|---:|
              | Electricity import | {{ ('£%.2f' | format((kems.get('electricity_import_cost_pence') | float) / 100)) if kems.get('electricity_import_cost_pence') is not none else '—' }} |
              | Standing charge | {{ ('£%.2f' | format((kems.get('electricity_standing_charge_pence') | float) / 100)) if kems.get('electricity_standing_charge_pence') is not none else '—' }} |
              | Export income | {{ ('−£%.2f' | format((kems.get('electricity_export_income_pence') | float) / 100)) if kems.get('electricity_export_income_pence') is not none else '—' }} |
              | Supplier credits | {{ ('−£%.2f' | format((kems.get('supplier_energy_credit_pence') | float) / 100)) if kems.get('supplier_energy_credit_pence') is not none else '—' }} |
              | **Electricity total** | **{{ ('£%.2f' | format((kems.get('electricity_total_cost_pence') | float) / 100)) if kems.get('electricity_total_cost_pence') is not none else '—' }}** |
              | Gas | {{ ('£%.2f' | format((kems.get('gas_total_cost_pence') | float) / 100)) if kems.get('gas_total_cost_pence') is not none else '—' }} |
              | **TOTAL ENERGY COST** | **{{ ('£%.2f' | format((kems.get('total_energy_cost_pence') | float) / 100)) if kems.get('total_energy_cost_pence') is not none else '—' }}** |"""

_KEMS_DAILY_NEW = """              {% set net = states('sensor.kems_simulated_kems_cost_today') | float(0) %}
              {% set gas = states('sensor.kems_gas_cost_today') | float(0) %}
              {% set total = states('sensor.kems_whole_home_simulated_cost_today') | float(net + gas) %}
              {% set export = states('sensor.kems_simulated_export_income_today') | float(0) %}
              {% set reward = states('sensor.kems_simulated_power_down_session_bonus_today') | float(0) %}
              {% set standing = [total - gas - net, 0] | max %}
              | Cost | KEMS |
              |---|---:|
              | Electricity net before standing | £{{ '%.2f' | format(net / 100) }} |
              | Standing charge | £{{ '%.2f' | format(standing / 100) }} |
              | Export income | −£{{ '%.2f' | format(export / 100) }} |
              | Supplier rewards & credits | −£{{ '%.2f' | format(reward / 100) }} |
              | **Electricity total** | **£{{ '%.2f' | format((total - gas) / 100) }}** |
              | Gas | £{{ '%.2f' | format(gas / 100) }} |
              | **TOTAL ENERGY COST** | **£{{ '%.2f' | format(total / 100) }}** |"""

_KEMS_HOME_ENERGY_OLD = """          {% set p = ((state_attr('sensor.kems_energy_cost_comparison', 'periods') or {}).get('today', {}) or {}) %}
          {% set kems = p.get('kems', {}) or {} %}
          | Energy | KEMS |
          |---|---:|
          | Whole-home energy | {{ (kems.get('home_energy_kwh') ~ ' kWh') if kems.get('home_energy_kwh') is not none else '—' }} |"""

_KEMS_HOME_ENERGY_NEW = """          | Energy | KEMS |
          |---|---:|
          | Whole-home energy | {{ states('sensor.kems_whole_home_energy_today') }} kWh |"""

_HOME_RECONCILED_OLD = """          {% set live_e = states('sensor.kems_observed_cost_today') | float(0) %}
          {% set kems_e = states('sensor.kems_simulated_kems_cost_today') | float(0) %}
          {% set gas = states('sensor.kems_gas_cost_today') | float(0) %}
          {% set bill_periods = state_attr('sensor.kems_energy_cost_comparison', 'periods') or {} %}
          {% set bill = bill_periods.get('today', {}) or {} %}
          {% set live_bill = bill.get('live_data', {}) or {} %}
          {% set kems_bill = bill.get('kems', {}) or {} %}
          {% set live_total = live_bill.get('total_energy_cost_pence') %}
          {% set kems_total = kems_bill.get('total_energy_cost_pence') %}
          {% set saving = bill.get('saving_pence') %}"""

_HOME_RECONCILED_NEW = """          {% set live_e = states('sensor.kems_observed_cost_today') | float(0) %}
          {% set kems_e = states('sensor.kems_simulated_kems_cost_today') | float(0) %}
          {% set gas = states('sensor.kems_gas_cost_today') | float(0) %}
          {% set live_total = states('sensor.kems_whole_home_observed_cost_today') | float(live_e + gas) %}
          {% set kems_total = states('sensor.kems_whole_home_simulated_cost_today') | float(kems_e + gas) %}
          {% set saving = live_total - kems_total %}"""

_KEMS_DAILY_CARD_NEW = """          - type: markdown
            title: Daily costs
            content: |
              {% set net = states('sensor.kems_simulated_kems_cost_today') | float(0) %}
              {% set gas = states('sensor.kems_gas_cost_today') | float(0) %}
              {% set total = states('sensor.kems_whole_home_simulated_cost_today') | float(net + gas) %}
              {% set export = states('sensor.kems_simulated_export_income_today') | float(0) %}
              {% set reward = states('sensor.kems_simulated_power_down_session_bonus_today') | float(0) %}
              {% set standing = [total - gas - net, 0] | max %}
              | Cost | KEMS |
              |---|---:|
              | Electricity net before standing | £{{ '%.2f' | format(net / 100) }} |
              | Standing charge | £{{ '%.2f' | format(standing / 100) }} |
              | Export income | −£{{ '%.2f' | format(export / 100) }} |
              | Supplier rewards & credits | −£{{ '%.2f' | format(reward / 100) }} |
              | **Electricity total** | **£{{ '%.2f' | format((total - gas) / 100) }}** |
              | Gas | £{{ '%.2f' | format(gas / 100) }} |
              | **TOTAL ENERGY COST** | **£{{ '%.2f' | format(total / 100) }}** |
"""

_COMPARE_WITHOUT_KEMS_NEW = """          - type: markdown
            title: Without KEMS
            content: |
              {% set bad = ['unknown', 'unavailable', 'none', ''] %}
              {% set gas_state = states('sensor.kems_gas_cost_today') %}
              {% set gas = (gas_state | float(0)) if gas_state | lower not in bad else none %}
              {% set base_state = states('sensor.kems_compare_no_system_cost_today') %}
              {% set electricity = (base_state | float(0)) if base_state | lower not in bad else none %}
              {% set total = (electricity + gas) if electricity is not none and gas is not none else none %}
              {% set s = states.sensor.kems_compare_no_system_cost_today %}
              **Today total energy cost**  
              # {{ ('£%.2f' | format(total / 100)) if total is not none else '—' }}

              Electricity: {{ ('£%.2f' | format(electricity / 100)) if electricity is not none else '—' }}  
              Gas: {{ ('£%.2f' | format(gas / 100)) if gas is not none else '—' }}  
              Grid import: {{ (s.attributes.grid_import_kwh ~ ' kWh') if s and s.attributes.grid_import_kwh is not none else '—' }}  
              Grid export: {{ (s.attributes.grid_export_kwh ~ ' kWh') if s and s.attributes.grid_export_kwh is not none else '0 kWh' }}

              _Counterfactual no-system replay._
"""

_COMPARE_LIVE_NEW = """          - type: markdown
            title: Live
            content: |
              {% set bad = ['unknown', 'unavailable', 'none', ''] %}
              {% set total_state = states('sensor.kems_whole_home_observed_cost_today') %}
              {% set total = (total_state | float(0)) if total_state | lower not in bad else none %}
              {% set gas_state = states('sensor.kems_gas_cost_today') %}
              {% set gas = (gas_state | float(0)) if gas_state | lower not in bad else none %}
              {% set electricity = (total - gas) if total is not none and gas is not none else none %}
              **Today total energy cost**  
              # {{ ('£%.2f' | format(total / 100)) if total is not none else '—' }}

              Electricity: {{ ('£%.2f' | format(electricity / 100)) if electricity is not none else '—' }}  
              Gas: {{ ('£%.2f' | format(gas / 100)) if gas is not none else '—' }}  
              Grid import: {{ states('sensor.kems_observed_grid_import_today') }} kWh  
              Grid export: {{ states('sensor.kems_observed_grid_export_today') }} kWh

              _Measured property data._
"""

_COMPARE_KEMS_NEW = """          - type: markdown
            title: KEMS
            content: |
              {% set bad = ['unknown', 'unavailable', 'none', ''] %}
              {% set gas_state = states('sensor.kems_gas_cost_today') %}
              {% set gas = (gas_state | float(0)) if gas_state | lower not in bad else none %}
              {% set kems_state = states('sensor.kems_compare_full_kems_cost_today') %}
              {% set electricity = (kems_state | float(0)) if kems_state | lower not in bad else none %}
              {% set total = (electricity + gas) if electricity is not none and gas is not none else none %}
              {% set s = states.sensor.kems_compare_full_kems_cost_today %}
              **Today total energy cost**  
              # {{ ('£%.2f' | format(total / 100)) if total is not none else '—' }}

              Electricity: {{ ('£%.2f' | format(electricity / 100)) if electricity is not none else '—' }}  
              Gas: {{ ('£%.2f' | format(gas / 100)) if gas is not none else '—' }}  
              Grid import: {{ (s.attributes.grid_import_kwh ~ ' kWh') if s and s.attributes.grid_import_kwh is not none else '—' }}  
              Grid export: {{ (s.attributes.grid_export_kwh ~ ' kWh') if s and s.attributes.grid_export_kwh is not none else '—' }}

              _Configured KEMS digital twin._
"""

_COMPARE_SIDE_BY_SIDE_NEW = """      - type: markdown
        title: Today — side by side
        content: |
          {% set bad = ['unknown', 'unavailable', 'none', ''] %}
          {% set gas_state = states('sensor.kems_gas_cost_today') %}
          {% set gas = (gas_state | float(0)) if gas_state | lower not in bad else none %}
          {% set base_state = states('sensor.kems_compare_no_system_cost_today') %}
          {% set base_e = (base_state | float(0)) if base_state | lower not in bad else none %}
          {% set live_state = states('sensor.kems_whole_home_observed_cost_today') %}
          {% set live_total = (live_state | float(0)) if live_state | lower not in bad else none %}
          {% set live_e = (live_total - gas) if live_total is not none and gas is not none else none %}
          {% set kems_state = states('sensor.kems_compare_full_kems_cost_today') %}
          {% set kems_e = (kems_state | float(0)) if kems_state | lower not in bad else none %}
          {% set base_total = (base_e + gas) if base_e is not none and gas is not none else none %}
          {% set kems_total = (kems_e + gas) if kems_e is not none and gas is not none else none %}
          | Metric | Without KEMS | Live | KEMS |
          |---|---:|---:|---:|
          | Total energy cost | {{ ('£%.2f' | format(base_total / 100)) if base_total is not none else '—' }} | {{ ('£%.2f' | format(live_total / 100)) if live_total is not none else '—' }} | {{ ('£%.2f' | format(kems_total / 100)) if kems_total is not none else '—' }} |
          | Electricity | {{ ('£%.2f' | format(base_e / 100)) if base_e is not none else '—' }} | {{ ('£%.2f' | format(live_e / 100)) if live_e is not none else '—' }} | {{ ('£%.2f' | format(kems_e / 100)) if kems_e is not none else '—' }} |
          | Gas | {{ ('£%.2f' | format(gas / 100)) if gas is not none else '—' }} | {{ ('£%.2f' | format(gas / 100)) if gas is not none else '—' }} | {{ ('£%.2f' | format(gas / 100)) if gas is not none else '—' }} |
          | Grid import | {{ state_attr('sensor.kems_compare_no_system_cost_today', 'grid_import_kwh') or '—' }} | {{ states('sensor.kems_observed_grid_import_today') }} | {{ state_attr('sensor.kems_compare_full_kems_cost_today', 'grid_import_kwh') or '—' }} |
          | Grid export | {{ state_attr('sensor.kems_compare_no_system_cost_today', 'grid_export_kwh') or 0 }} | {{ states('sensor.kems_observed_grid_export_today') }} | {{ state_attr('sensor.kems_compare_full_kems_cost_today', 'grid_export_kwh') or '—' }} |

          {% if base_total is not none and live_total is not none %}
          **Live system value vs no system:** £{{ '%.2f' | format((base_total - live_total) / 100) }}
          {% endif %}
          {% if base_total is not none and kems_total is not none %}
          **KEMS potential value vs no system:** £{{ '%.2f' | format((base_total - kems_total) / 100) }}
          {% endif %}
"""


def _replace_between(content: str, start: str, end: str, replacement: str) -> str:
    """Replace one deterministic dashboard region without touching later periods."""
    begin = content.find(start)
    if begin < 0:
        return content
    finish = content.find(end, begin + len(start))
    if finish < 0:
        return content
    return content[:begin] + replacement.rstrip() + "\n" + content[finish:]


def _improve_alpha910_today_presentation(content: str) -> str:
    """Keep live current-day cards independent of incomplete period settlement."""
    content = content.replace(_HOME_RECONCILED_OLD, _HOME_RECONCILED_NEW)

    kems_view = content.find("\n  - title: KEMS\n")
    compare_view = content.find("\n  - title: Compare\n", kems_view + 1)
    if kems_view >= 0 and compare_view > kems_view:
        kems = content[kems_view:compare_view]
        kems = _replace_between(
            kems,
            "          - type: markdown\n            title: Daily costs\n",
            "      - type: markdown\n        title: Energy today\n",
            _KEMS_DAILY_CARD_NEW,
        )
        content = content[:kems_view] + kems + content[compare_view:]

    compare_view = content.find("\n  - title: Compare\n")
    if compare_view < 0:
        return content
    next_view = content.find("\n  - title:", compare_view + len("\n  - title: Compare\n"))
    if next_view < 0:
        next_view = len(content)
    compare = content[compare_view:next_view]
    compare = _replace_between(
        compare,
        "          - type: markdown\n            title: Without KEMS\n",
        "          - type: markdown\n            title: Live\n",
        _COMPARE_WITHOUT_KEMS_NEW,
    )
    compare = _replace_between(
        compare,
        "          - type: markdown\n            title: Live\n",
        "          - type: markdown\n            title: KEMS\n",
        _COMPARE_LIVE_NEW,
    )
    compare = _replace_between(
        compare,
        "          - type: markdown\n            title: KEMS\n",
        "      - type: markdown\n        title: Today — side by side\n",
        _COMPARE_KEMS_NEW,
    )
    compare = _replace_between(
        compare,
        "      - type: markdown\n        title: Today — side by side\n",
        "      - type: history-graph\n        title: Electricity cost — Live vs KEMS\n",
        _COMPARE_SIDE_BY_SIDE_NEW,
    )
    return content[:compare_view] + compare + content[next_view:]


def improve_alpha95_dashboard(content: str) -> str:
    """Use stable flat current-day entities and defensive update-status templates."""
    content = (
        content.replace(_LIVE_DAILY_OLD, _LIVE_DAILY_NEW)
        .replace(_KEMS_DAILY_OLD, _KEMS_DAILY_NEW)
        .replace(_KEMS_HOME_ENERGY_OLD, _KEMS_HOME_ENERGY_NEW)
        .replace(
            "{{ u.attributes.running_kems_version if u else '—' }}",
            "{{ (u.attributes.get('running_kems_version') or '—') if u else '—' }}",
        )
        .replace(
            "{{ u.attributes.bundle if u and u.attributes.bundle else '—' }}",
            "{{ (u.attributes.get('bundle') or '—') if u else '—' }}",
        )
        .replace(
            "{{ u.attributes.last_result if u and u.attributes.last_result else '—' }}",
            "{{ (u.attributes.get('last_result') or '—') if u else '—' }}",
        )
        .replace(
            "{% if u and u.attributes.last_error %}",
            "{% if u and u.attributes.get('last_error') %}",
        )
        .replace(
            "{{ u.attributes.last_error }}",
            "{{ u.attributes.get('last_error') }}",
        )
    )
    return _improve_alpha910_today_presentation(content)


def _improve_dashboard_bytes(payload: bytes) -> bytes:
    """Apply the presentation repair to the authoritative managed-dashboard bytes."""
    return improve_alpha95_dashboard(payload.decode("utf-8")).encode("utf-8")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _state_with_panel_soc(
    manager: Any,
    state: dict[str, Any],
    fallback_soc: Any = None,
) -> dict[str, Any]:
    """Fill only the reporting snapshot SOC when its simulation value is absent."""
    snapshot = state.get("current_routing_snapshot")
    if not isinstance(snapshot, dict):
        return state
    if _finite(snapshot.get("simulated_soc_percent")) is not None:
        return state

    soc = _finite(fallback_soc)
    if soc is None:
        simulated = manager._hass.states.get(_SIMULATED_SOC_ENTITY)
        soc = _finite(simulated.state if simulated is not None else None)
    if soc is None:
        return state

    enriched = dict(state)
    enriched_snapshot = dict(snapshot)
    enriched_snapshot["simulated_soc_percent"] = soc
    enriched["current_routing_snapshot"] = enriched_snapshot
    return enriched


def _panel_flow(snapshot: dict[str, Any]) -> str:
    """Preserve valid virtual SOC even when instantaneous routing is unavailable."""
    flow = panel_runtime._compact_flow(snapshot)
    soc = _finite(snapshot.get("simulated_soc_percent"))
    if soc is None or "SOC=-1" not in flow:
        return flow
    return flow.rsplit("SOC=", 1)[0] + f"SOC={soc:.1f}"


def _publish_panel_flow_state(manager: Any, state: dict[str, Any]) -> None:
    """Project compact panel state without invoking or rewiring a publisher."""
    snapshot = state.get("current_routing_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {"available": False}

    flow = _panel_flow(snapshot)
    attributes = {
        "version": "0.7.0-alpha7.36",
        "source": "current_routing_snapshot",
        "reporting_only": True,
        "routing_action": snapshot.get("routing_action"),
        "dispatch_mode": snapshot.get("dispatch_mode"),
        "simulated_soc_percent": snapshot.get("simulated_soc_percent"),
    }
    manager._set(panel_runtime._LEGACY_PANEL_FLOW_SENSOR, flow, attributes)
    manager._set(panel_runtime._PANEL_FLOW_SENSOR, flow, attributes)

    live_state = manager._hass.states.get(panel_runtime._LIVE_SENSOR)
    if live_state is not None:
        live_attributes = dict(live_state.attributes)
        live_attributes["simulated_soc_percent"] = snapshot.get("simulated_soc_percent")
        live_attributes["panel_flow_state"] = flow
        live_attributes["panel_flow_source"] = panel_runtime._PANEL_FLOW_SENSOR
        manager._set(panel_runtime._LIVE_SENSOR, live_state.state, live_attributes)


def publish_alpha98_panel_projection(manager: Any, simulated_soc_percent: Any) -> None:
    """Republish startup panel state with the coordinator's valid virtual SOC."""
    state = manager.state
    if not isinstance(state, dict) or not state:
        return
    enriched = _state_with_panel_soc(manager, state, simulated_soc_percent)
    _publish_panel_flow_state(manager, enriched)


def install_alpha95_presentation() -> None:
    """Install the presentation repair exactly once without rewiring legacy globals."""
    from . import dashboard
    from . import update_orchestrator_convergent as convergent

    dashboard_bytes = dashboard._combined_master_dashboard_bytes
    if not getattr(dashboard_bytes, "_kems_alpha95_flat_daily", False):

        def dashboard_bytes_with_alpha95() -> bytes:
            return _improve_dashboard_bytes(dashboard_bytes())

        dashboard_bytes_with_alpha95._kems_alpha95_flat_daily = True
        dashboard._combined_master_dashboard_bytes = dashboard_bytes_with_alpha95
        convergent._managed_dashboard_bytes = dashboard_bytes_with_alpha95

    publish = agile_runtime.EfficientAgileSmartExportManager._publish
    if getattr(publish, "_kems_alpha95_panel_soc", False):
        return

    # The compatibility chain already installed the historical panel wrapper once.
    # Reinstalling it here would overwrite that module's global original-publisher
    # pointer with a later chain that already contains the first wrapper, creating
    # an immediate recursion loop. Wrap only the final publisher and project the
    # panel state directly after the existing chain completes.
    original_publish = publish

    def publish_with_alpha95_panel_soc(self: Any, state: dict[str, Any]) -> None:
        original_publish(self, state)
        enriched = _state_with_panel_soc(self, state)
        _publish_panel_flow_state(self, enriched)

    publish_with_alpha95_panel_soc._kems_alpha95_panel_soc = True
    publish_with_alpha95_panel_soc._kems_alpha736_panel_flow = True
    agile_runtime.EfficientAgileSmartExportManager._publish = (
        publish_with_alpha95_panel_soc
    )
