"""Alpha9.5 customer presentation repair, hardened by Alpha9.6.

Keep current-day dashboard totals on the stable flat KEMS entities and restore the
HA-side Full KEMS Agile panel flow publisher.  This module is reporting-only: it
does not alter optimisation, control eligibility, FoxESS commissioning, or any
hardware-write boundary.
"""

# ruff: noqa: E501

from __future__ import annotations

import math
from typing import Any

from . import agile_smart_export_runtime_base as agile_runtime
from .agile_panel_presentation_runtime import install_alpha736_panel_flow_patch

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
              {% set standing = [total - gas - net, 0] | max %}
              | Cost | KEMS |
              |---|---:|
              | Electricity net before standing | £{{ '%.2f' | format(net / 100) }} |
              | Standing charge | £{{ '%.2f' | format(standing / 100) }} |
              | Export income | −£{{ '%.2f' | format(export / 100) }} |
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


def improve_alpha95_dashboard(content: str) -> str:
    """Use stable flat current-day entities and defensive update-status templates."""
    return (
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


def _improve_dashboard_bytes(payload: bytes) -> bytes:
    """Apply the presentation repair to the authoritative managed-dashboard bytes."""
    return improve_alpha95_dashboard(payload.decode("utf-8")).encode("utf-8")


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _state_with_panel_soc(manager: Any, state: dict[str, Any]) -> dict[str, Any]:
    """Fill only the reporting snapshot SOC when its simulation value is absent."""
    snapshot = state.get("current_routing_snapshot")
    if not isinstance(snapshot, dict):
        return state
    if _finite(snapshot.get("simulated_soc_percent")) is not None:
        return state

    simulated = manager._hass.states.get(_SIMULATED_SOC_ENTITY)
    soc = _finite(simulated.state if simulated is not None else None)
    if soc is None:
        return state

    enriched = dict(state)
    enriched_snapshot = dict(snapshot)
    enriched_snapshot["simulated_soc_percent"] = soc
    enriched["current_routing_snapshot"] = enriched_snapshot
    return enriched


def install_alpha95_presentation() -> None:
    """Install the Alpha9.5 presentation repair exactly once across HA retries."""
    from . import dashboard
    from . import update_orchestrator_convergent as convergent

    dashboard_bytes = dashboard._combined_master_dashboard_bytes
    if not getattr(dashboard_bytes, "_kems_alpha95_flat_daily", False):

        def dashboard_bytes_with_alpha95() -> bytes:
            return _improve_dashboard_bytes(dashboard_bytes())

        dashboard_bytes_with_alpha95._kems_alpha95_flat_daily = True
        dashboard._combined_master_dashboard_bytes = dashboard_bytes_with_alpha95
        convergent._managed_dashboard_bytes = dashboard_bytes_with_alpha95

    # A failed Home Assistant setup is retried in the same Python process. Once
    # Alpha9.5 already owns the publisher, return before calling the older panel
    # installer again; reinstalling it would rewrite its global original-publish
    # pointer back to this wrapper and create an infinite recursion loop.
    publish = agile_runtime.EfficientAgileSmartExportManager._publish
    if getattr(publish, "_kems_alpha95_panel_soc", False):
        return

    # Restore the HA-side compact flow publisher expected by the already-shipped
    # alpha9-panel.0 firmware. No panel firmware change is required.
    install_alpha736_panel_flow_patch()

    publish = agile_runtime.EfficientAgileSmartExportManager._publish
    original_publish = publish

    def publish_with_alpha95_panel_soc(self: Any, state: dict[str, Any]) -> None:
        original_publish(self, _state_with_panel_soc(self, state))

    publish_with_alpha95_panel_soc._kems_alpha95_panel_soc = True
    if getattr(original_publish, "_kems_alpha736_panel_flow", False):
        publish_with_alpha95_panel_soc._kems_alpha736_panel_flow = True
    agile_runtime.EfficientAgileSmartExportManager._publish = (
        publish_with_alpha95_panel_soc
    )
