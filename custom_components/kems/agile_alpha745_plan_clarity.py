"""Alpha7.45 battery-plan clarity for the focused Full KEMS Agile dashboard.

Alpha7.44's half-hour decision table deliberately showed only executable
known-price allocations. During a bounded partial price horizon that can make a
correct plan look too small because unresolved future slots retain their full
discharge capacity as a safety reservation rather than a guessed export
allocation.

Alpha7.45 makes that distinction visible. It does not change the optimiser. It
publishes current simulated SOC, the 10% target, protected house energy,
known-price export allocations, unpublished-slot capacity reservation and any
true unaccounted export requirement. The dashboard also exposes physical SOC
when available and makes missing physical battery data explicit.

Real FoxESS hardware writes remain blocked.
"""

# ruff: noqa: E501

from __future__ import annotations

import math
from typing import Any

from . import agile_smart_export_runtime_base as runtime
from .kems_core import SimulationConfig

_PLAN_SUMMARY = "sensor.kems_agile_battery_plan_summary"
_ALPHA745_SENSOR_IDS = (_PLAN_SUMMARY,)

_SLOT_CARD_MARKER = """      - type: markdown
        title: Today's Agile half-hour slots and decisions
"""

_BATTERY_PLAN_CARD = r"""      - type: markdown
        title: Battery plan to next cheap period
        content: |
          {% set p = state_attr('sensor.kems_agile_battery_plan_summary', 'plan') or {} %}
          | Battery plan | Current |
          |---|---:|
          | Simulated SOC now | **{{ p.get('simulated_soc_percent', '—') }}{% if p.get('simulated_soc_percent') is not none %}%{% endif %}** |
          | Target SOC at cheap-period start | **{{ p.get('target_soc_percent', '—') }}{% if p.get('target_soc_percent') is not none %}%{% endif %}** |
          | Protected house energy | {{ p.get('protected_house_energy_kwh', '—') }}{% if p.get('protected_house_energy_kwh') is not none %} kWh{% endif %} |
          | Exportable battery energy | {{ p.get('exportable_battery_energy_kwh', '—') }}{% if p.get('exportable_battery_energy_kwh') is not none %} kWh{% endif %} |
          | Planned in published-price slots | {{ p.get('known_price_planned_export_kwh', '—') }}{% if p.get('known_price_planned_export_kwh') is not none %} kWh{% endif %} |
          | Capacity reserved for unpublished slots | {{ p.get('unknown_price_capacity_reserved_kwh', '—') }}{% if p.get('unknown_price_capacity_reserved_kwh') is not none %} kWh{% endif %} |
          | Still required from unpublished slots | {{ p.get('required_from_unknown_slots_kwh', '—') }}{% if p.get('required_from_unknown_slots_kwh') is not none %} kWh{% endif %} |
          | Truly unaccounted export requirement | **{{ p.get('unaccounted_export_requirement_kwh', '—') }}{% if p.get('unaccounted_export_requirement_kwh') is not none %} kWh{% endif %}** |
          | Projected SOC after published plan only | {{ p.get('projected_soc_after_known_plan_percent', '—') }}{% if p.get('projected_soc_after_known_plan_percent') is not none %}%{% endif %} |
          | Projected SOC if reserved unknown capacity is used | **{{ p.get('projected_soc_with_reserved_capacity_percent', '—') }}{% if p.get('projected_soc_with_reserved_capacity_percent') is not none %}%{% endif %}** |

          **Target status:** {{ p.get('target_status', 'Waiting for plan') }}

          {% set missing = p.get('unresolved_price_slots') or [] %}{% if missing %}Unpublished relevant slot(s): **{{ missing | join(', ') }}**. KEMS is reserving capacity for these slots without inventing a price.{% endif %}

"""

_SIM_SOC_ROW_MARKER = """              | Battery net | {{ states('sensor.kems_agile_simulated_battery_net_power') }} kW |
"""
_SIM_SOC_ROW = (
    _SIM_SOC_ROW_MARKER
    + """              | Battery SOC | **{{ states('sensor.kems_agile_simulated_battery_soc_now') }}%** |
"""
)

_LIVE_SOC_ROW_MARKER = """              | Battery power | {{ states('sensor.kems_battery_power') if states('sensor.kems_battery_power') not in ['unknown','unavailable'] else '—' }}{% if states('sensor.kems_battery_power') not in ['unknown','unavailable'] %} kW{% endif %} |
"""
_LIVE_SOC_ROW = (
    _LIVE_SOC_ROW_MARKER
    + """              | Battery SOC | {{ states('sensor.kems_battery_state_of_charge') if states('sensor.kems_battery_state_of_charge') not in ['unknown','unavailable'] else '—' }}{% if states('sensor.kems_battery_state_of_charge') not in ['unknown','unavailable'] %}%{% endif %} |
"""
)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _plan_summary(self) -> dict[str, Any]:
    state = self._hass.states.get("sensor.kems_agile_rolling_export_plan")
    attrs = dict(state.attributes) if state is not None else {}
    config = getattr(self, "_rolling_config", None)

    soc = _number(attrs.get("simulated_soc_percent"))
    target = _number(attrs.get("target_soc_percent"))
    protected_house = _number(attrs.get("protected_house_energy_kwh"))
    exportable = _number(attrs.get("exportable_battery_energy_kwh"))
    planned = _number(attrs.get("planned_battery_export_kwh"))
    reserved = max(
        _number(attrs.get("bounded_unknown_capacity_reserved_kwh")) or 0.0,
        _number(attrs.get("provisional_reserved_unknown_capacity_kwh")) or 0.0,
    )
    planned = max(planned or 0.0, 0.0)
    exportable = max(exportable or 0.0, 0.0)
    gap_after_known = max(exportable - planned, 0.0)
    required_from_unknown = min(gap_after_known, reserved)
    unaccounted = max(gap_after_known - reserved, 0.0)

    projected_known = None
    projected_reserved = None
    if (
        target is not None
        and isinstance(config, SimulationConfig)
        and config.battery_capacity_kwh > 0
    ):
        efficiency = max(float(config.discharge_efficiency), 0.01)
        capacity = max(float(config.battery_capacity_kwh), 0.1)
        projected_known = target + (gap_after_known / efficiency / capacity * 100.0)
        projected_reserved = target + (unaccounted / efficiency / capacity * 100.0)
        projected_known = round(min(max(projected_known, target), 100.0), 1)
        projected_reserved = round(min(max(projected_reserved, target), 100.0), 1)

    tolerance = 0.01
    if exportable <= tolerance:
        target_status = (
            "No discretionary export required — house and reserve are protected"
        )
    elif gap_after_known <= tolerance:
        target_status = "Covered by published-price export plan"
    elif reserved + tolerance >= gap_after_known:
        target_status = "Covered — published exports plus reserved unpublished-slot capacity can reach target"
    else:
        target_status = (
            f"Shortfall {unaccounted:.3f} kWh — more export capacity is required"
        )

    unresolved = attrs.get("provisional_unresolved_price_slots")
    unresolved = [str(item) for item in unresolved or [] if str(item).strip()]

    return {
        "simulated_soc_percent": round(soc, 1) if soc is not None else None,
        "target_soc_percent": round(target, 1) if target is not None else None,
        "protected_house_energy_kwh": (
            round(protected_house, 3) if protected_house is not None else None
        ),
        "exportable_battery_energy_kwh": round(exportable, 3),
        "known_price_planned_export_kwh": round(planned, 3),
        "unknown_price_capacity_reserved_kwh": round(reserved, 3),
        "required_from_unknown_slots_kwh": round(required_from_unknown, 3),
        "unaccounted_export_requirement_kwh": round(unaccounted, 3),
        "projected_soc_after_known_plan_percent": projected_known,
        "projected_soc_with_reserved_capacity_percent": projected_reserved,
        "target_status": target_status,
        "target_covered": unaccounted <= tolerance,
        "unresolved_price_slots": unresolved,
        "bounded_partial_horizon": bool(
            attrs.get("bounded_partial_horizon_dispatch_active")
        ),
        "unknown_prices_are_never_guessed": True,
        "reporting_only": True,
        "hardware_writes": "blocked",
    }


def _annotate_unknown_slot_rows(self, plan: dict[str, Any]) -> None:
    slot_state = self._hass.states.get("sensor.kems_agile_slot_decisions_today")
    if slot_state is None:
        return
    attrs = dict(slot_state.attributes)
    slots = [dict(item) for item in attrs.get("slots", []) if isinstance(item, dict)]
    if not slots:
        return

    rolling = self._hass.states.get("sensor.kems_agile_rolling_export_plan")
    rolling_attrs = dict(rolling.attributes) if rolling is not None else {}
    effective_kw = max(_number(rolling_attrs.get("effective_discharge_kw")) or 0.0, 0.0)
    remaining_need = max(
        _number(plan.get("required_from_unknown_slots_kwh")) or 0.0, 0.0
    )

    for row in slots:
        decision = str(row.get("decision") or "")
        if not decision.startswith("Waiting for Octopus price"):
            continue
        slot_capacity = round(effective_kw * 0.5, 3)
        needed_here = min(remaining_need, slot_capacity)
        row["reserved_unknown_slot_capacity_kwh"] = slot_capacity
        row["currently_needed_from_this_unknown_capacity_kwh"] = round(needed_here, 3)
        row["decision"] = (
            f"Waiting for Octopus price — {slot_capacity:.3f} kWh capacity reserved"
            + (f"; {needed_here:.3f} kWh currently needed" if needed_here > 0.0 else "")
        )
        remaining_need = max(remaining_need - needed_here, 0.0)

    attrs["slots"] = slots
    attrs["battery_plan_summary"] = plan
    self._set("sensor.kems_agile_slot_decisions_today", slot_state.state, attrs)


def improve_alpha745_dashboard(content: str) -> str:
    if "title: Battery plan to next cheap period" not in content:
        if _SLOT_CARD_MARKER not in content:
            raise ValueError("Alpha7.45 slot decision dashboard marker missing")
        content = content.replace(
            _SLOT_CARD_MARKER,
            _BATTERY_PLAN_CARD + _SLOT_CARD_MARKER,
            1,
        )
    if (
        _SIM_SOC_ROW_MARKER in content
        and "| Battery SOC | **{{ states('sensor.kems_agile_simulated_battery_soc_now') }}%** |"
        not in content
    ):
        content = content.replace(_SIM_SOC_ROW_MARKER, _SIM_SOC_ROW, 1)
    if (
        _LIVE_SOC_ROW_MARKER in content
        and "sensor.kems_battery_state_of_charge" not in content
    ):
        content = content.replace(_LIVE_SOC_ROW_MARKER, _LIVE_SOC_ROW, 1)
    return content


def install_alpha745_plan_clarity_patch() -> None:
    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_alpha745_plan_clarity", False):
        original_publish = publish

        def publish_with_alpha745(self, state: dict[str, Any]) -> None:
            original_publish(self, state)
            plan = _plan_summary(self)
            self._set(
                _PLAN_SUMMARY,
                plan.get("target_status") or "Waiting for plan",
                {
                    "friendly_name": "Full KEMS Agile battery plan summary",
                    "plan": plan,
                    **plan,
                },
            )
            _annotate_unknown_slot_rows(self, plan)

        publish_with_alpha745._kems_alpha745_plan_clarity = True
        runtime.EfficientAgileSmartExportManager._publish = publish_with_alpha745

    shutdown = runtime.EfficientAgileSmartExportManager.async_shutdown
    if not getattr(shutdown, "_kems_alpha745_plan_clarity", False):
        original_shutdown = shutdown

        async def shutdown_with_alpha745(self) -> None:
            await original_shutdown(self)
            for entity_id in _ALPHA745_SENSOR_IDS:
                self._hass.states.async_remove(entity_id)

        shutdown_with_alpha745._kems_alpha745_plan_clarity = True
        runtime.EfficientAgileSmartExportManager.async_shutdown = shutdown_with_alpha745

    from . import dashboard as dashboard_module

    combined = dashboard_module._combined_master_dashboard_bytes
    if getattr(combined, "_kems_alpha745_plan_clarity", False):
        return
    original_dashboard = combined

    def combined_alpha745_dashboard() -> bytes:
        content = original_dashboard().decode("utf-8")
        return improve_alpha745_dashboard(content).encode("utf-8")

    combined_alpha745_dashboard._kems_alpha745_plan_clarity = True
    dashboard_module._combined_master_dashboard_bytes = combined_alpha745_dashboard
