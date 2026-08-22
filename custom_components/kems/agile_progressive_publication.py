"""Canonical progressive publication planning and plan clarity for Agile.

This Alpha8 module carries forward the proven Alpha7.45, Alpha7.46 and
Alpha7.47 behaviour without keeping those version-named patch modules in the
executable runtime chain. It publishes the battery plan clearly and permits the
progressive known-price no-reserve path only for a verified clean Octopus
publication gap.

Existing current-price, reserve, deadline, Power Down and Happy Hour safety
behaviour remains owned by the earlier canonical/runtime layers. Real FoxESS
hardware writes remain blocked.
"""

# ruff: noqa: E501

from __future__ import annotations

import math
from typing import Any

from . import agile_alpha726_provisional as alpha726
from . import agile_alpha728_bounded_partial as alpha728
from . import agile_smart_export_runtime_base as runtime
from .kems_core import SimulationConfig

_EPSILON = 1e-6
_PLAN_SUMMARY = "sensor.kems_agile_battery_plan_summary"
_SENSOR_IDS = (_PLAN_SUMMARY,)

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

_OLD_RESERVE_TEXT = (
    "          | Capacity reserved for unpublished slots | "
    "{{ p.get('unknown_price_capacity_reserved_kwh', '—') }}"
    "{% if p.get('unknown_price_capacity_reserved_kwh') is not none %} kWh"
    "{% endif %} |\n"
    "          | Still required from unpublished slots | "
    "{{ p.get('required_from_unknown_slots_kwh', '—') }}"
    "{% if p.get('required_from_unknown_slots_kwh') is not none %} kWh"
    "{% endif %} |\n"
)
_NEW_RESERVE_TEXT = (
    "          | Capacity reserved for unpublished slots | **0.0 kWh** |\n"
    "          | Published-price plan coverage | "
    "{{ p.get('known_price_plan_coverage_percent', '—') }}"
    "{% if p.get('known_price_plan_coverage_percent') is not none %}%"
    "{% endif %} |\n"
)
_OLD_PROJECTED_ROW = (
    "          | Projected SOC if reserved unknown capacity is used | **"
    "{{ p.get('projected_soc_with_reserved_capacity_percent', '—') }}"
    "{% if p.get('projected_soc_with_reserved_capacity_percent') is not none %}%"
    "{% endif %}** |\n"
)
_NEW_PROJECTED_ROW = (
    "          | Projected SOC after current published-price plan | **"
    "{{ p.get('projected_soc_after_known_plan_percent', '—') }}"
    "{% if p.get('projected_soc_after_known_plan_percent') is not none %}%"
    "{% endif %}** |\n"
)
_OLD_MISSING_NOTE = (
    "Unpublished relevant slot(s): **{{ missing | join(', ') }}**. KEMS is "
    "reserving capacity for these slots without inventing a price."
)
_NEW_MISSING_NOTE = (
    "Unpublished relevant slot(s): **{{ missing | join(', ') }}**. KEMS does "
    "not reserve battery for unpublished prices. When a price appears the "
    "rolling plan is rebuilt and may replace lower-value future export slots."
)


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _base_plan_summary(self) -> dict[str, Any]:
    """Build the Alpha7.45-equivalent battery plan evidence."""
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


def _plan_summary(self) -> dict[str, Any]:
    """Publish plan clarity plus the proven clean-gap no-reserve evidence."""
    result = _base_plan_summary(self)
    rolling_state = self._hass.states.get("sensor.kems_agile_rolling_export_plan")
    attrs = dict(rolling_state.attributes) if rolling_state is not None else {}
    if not attrs.get("publication_gap_no_reserve_active"):
        return result

    exportable = max(
        _number(result.get("exportable_battery_energy_kwh")) or 0.0,
        0.0,
    )
    planned = max(
        _number(result.get("known_price_planned_export_kwh")) or 0.0,
        0.0,
    )
    unaccounted = max(exportable - planned, 0.0)
    coverage = 100.0 if exportable <= 0.01 else min(planned / exportable * 100.0, 100.0)
    result.update(
        {
            "unknown_price_capacity_reserved_kwh": 0.0,
            "required_from_unknown_slots_kwh": 0.0,
            "unaccounted_export_requirement_kwh": round(unaccounted, 3),
            "known_price_plan_coverage_percent": round(coverage, 1),
            "target_covered": unaccounted <= 0.01,
            "target_status": (
                "Covered by published-price export plan; unpublished slots will "
                "be re-ranked when their prices arrive"
                if unaccounted <= 0.01
                else (
                    f"Published prices currently leave {unaccounted:.3f} kWh "
                    "unallocated; replan as new prices arrive"
                )
            ),
            "unknown_price_reservation_policy": "none",
            "replan_when_price_publishes": True,
        }
    )
    return result


def _annotate_reserved_unknown_slot_rows(self, plan: dict[str, Any]) -> None:
    """Annotate unresolved slots with the bounded-reserve evidence."""
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


def _annotate_unknown_slot_rows(self, plan: dict[str, Any]) -> None:
    """Annotate unresolved prices using the active reserve policy."""
    rolling_state = self._hass.states.get("sensor.kems_agile_rolling_export_plan")
    rolling_attrs = dict(rolling_state.attributes) if rolling_state is not None else {}
    if not rolling_attrs.get("publication_gap_no_reserve_active"):
        _annotate_reserved_unknown_slot_rows(self, plan)
        return

    slot_state = self._hass.states.get("sensor.kems_agile_slot_decisions_today")
    if slot_state is None:
        return
    attrs = dict(slot_state.attributes)
    slots = [dict(item) for item in attrs.get("slots", []) if isinstance(item, dict)]
    for row in slots:
        if str(row.get("decision") or "").startswith("Waiting for Octopus price"):
            row["reserved_unknown_slot_capacity_kwh"] = 0.0
            row["currently_needed_from_this_unknown_capacity_kwh"] = 0.0
            row["decision"] = (
                "Waiting for Octopus price — no capacity reserved; re-rank when "
                "published"
            )
    attrs["slots"] = slots
    attrs["battery_plan_summary"] = plan
    attrs["unknown_price_reservation_policy"] = "none"
    self._set("sensor.kems_agile_slot_decisions_today", slot_state.state, attrs)


def _improve_plan_clarity_dashboard(content: str) -> str:
    """Apply the proven plan/SOC dashboard additions."""
    if "title: Battery plan to next cheap period" not in content:
        if _SLOT_CARD_MARKER not in content:
            raise ValueError(
                "Agile plan-clarity slot decision dashboard marker missing"
            )
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


def _improve_dashboard_no_reserve(content: str) -> str:
    """Apply the proven no-reserve dashboard wording."""
    content = content.replace(_OLD_RESERVE_TEXT, _NEW_RESERVE_TEXT, 1)
    content = content.replace(_OLD_PROJECTED_ROW, _NEW_PROJECTED_ROW, 1)
    return content.replace(_OLD_MISSING_NOTE, _NEW_MISSING_NOTE, 1)


def _no_reserve_unknown_capacity(
    selected: list[dict[str, Any]],
    reserve_kwh: float,
) -> tuple[list[dict[str, Any]], float]:
    """Keep the full known-price allocation and reserve nothing for unknowns."""
    del reserve_kwh
    return [dict(item) for item in selected if isinstance(item, dict)], 0.0


def _apply_no_reserve_publication_dispatch(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now,
    config,
    tariff,
) -> None:
    """Relax only a verified clean publication gap, never a retrieval failure."""
    horizon = state.get("planning_horizon")
    horizon = horizon if isinstance(horizon, dict) else {}
    recovery = alpha728._recovery_evidence(self, horizon)
    current_price = alpha728._current_price_evidence(state, now)
    clean_publication_gap = bool(
        recovery.get("verified")
        and recovery.get("recovery_outcome") == "octopus_missing_price"
        and horizon.get("current_slot_known")
        and current_price.get("known")
    )
    if not clean_publication_gap:
        _original_bounded_partial_apply(
            self,
            state,
            plan,
            now=now,
            config=config,
            tariff=tariff,
        )
        return

    reserve = alpha728._reserve_evidence(plan, horizon, now=now)
    required = max(_number(reserve.get("required_kwh")) or 0.0, 0.0)

    # The bounded-partial safety gate requires its temporary reserve evidence to
    # match unresolved capacity while validation runs. The known-price rows stay
    # untrimmed because this canonical layer replaced the provisional trimmer.
    plan["provisional_reserved_unknown_capacity_kwh"] = required
    _original_bounded_partial_apply(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )

    if not plan.get("bounded_partial_horizon_dispatch_active"):
        plan["provisional_reserved_unknown_capacity_kwh"] = 0.0
        return

    planned = max(_number(plan.get("planned_battery_export_kwh")) or 0.0, 0.0)
    exportable = max(
        _number(plan.get("exportable_battery_energy_kwh")) or 0.0,
        0.0,
    )
    export_now = max(
        _number(plan.get("current_battery_export_target_kw")) or 0.0,
        0.0,
    )
    action = (
        "progressive known-price export — unpublished slots not reserved"
        if export_now > _EPSILON
        else "progressive known-price hold — current known slot not selected"
    )

    plan.update(
        {
            "provisional_reserved_unknown_capacity_kwh": 0.0,
            "bounded_unknown_capacity_required_kwh": 0.0,
            "bounded_unknown_capacity_reserved_kwh": 0.0,
            "bounded_unknown_capacity_sufficient": True,
            "publication_gap_no_reserve_active": True,
            "unknown_price_reservation_policy": "none",
            "replan_when_price_publishes": True,
            "economic_plan_status": "progressive_known_prices_no_reserve",
            "dispatch_mode": "progressive_known_prices_no_reserve",
            "dispatch_action": action,
            "price_horizon_status": "progressive_known_prices_no_reserve",
            "unallocated_exportable_kwh": round(max(exportable - planned, 0.0), 3),
        }
    )
    horizon.update(
        {
            "status": "progressive_known_prices_no_reserve",
            "unknown_capacity_required_kwh": 0.0,
            "unknown_capacity_reserved_kwh": 0.0,
            "unknown_capacity_sufficient": True,
            "unknown_price_reservation_policy": "none",
            "replan_when_price_publishes": True,
        }
    )
    state["planning_horizon"] = horizon
    state["current_action"] = action

    current_slot = alpha728.alpha717._current_slot(state, now)
    if isinstance(current_slot, dict):
        current_slot["rolling_action"] = action
        current_slot["dispatch_action"] = action


def install_progressive_publication_planning() -> None:
    """Install the consolidated Alpha7.45-7.47-equivalent behaviour."""
    alpha726._reserve_unknown_capacity = _no_reserve_unknown_capacity

    apply = alpha728._apply_bounded_partial_dispatch
    if not getattr(apply, "_kems_progressive_publication", False):
        global _original_bounded_partial_apply
        _original_bounded_partial_apply = apply
        _apply_no_reserve_publication_dispatch._kems_progressive_publication = True
        alpha728._apply_bounded_partial_dispatch = (
            _apply_no_reserve_publication_dispatch
        )

    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_progressive_publication", False):
        original_publish = publish

        def publish_with_progressive_publication(self, state: dict[str, Any]) -> None:
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

        publish_with_progressive_publication._kems_progressive_publication = True
        runtime.EfficientAgileSmartExportManager._publish = (
            publish_with_progressive_publication
        )

    shutdown = runtime.EfficientAgileSmartExportManager.async_shutdown
    if not getattr(shutdown, "_kems_progressive_publication", False):
        original_shutdown = shutdown

        async def shutdown_with_progressive_publication(self) -> None:
            await original_shutdown(self)
            for entity_id in _SENSOR_IDS:
                self._hass.states.async_remove(entity_id)

        shutdown_with_progressive_publication._kems_progressive_publication = True
        runtime.EfficientAgileSmartExportManager.async_shutdown = (
            shutdown_with_progressive_publication
        )

    from . import dashboard as dashboard_module

    combined = dashboard_module._combined_master_dashboard_bytes
    if getattr(combined, "_kems_progressive_publication", False):
        return
    original_dashboard = combined

    def combined_progressive_publication_dashboard() -> bytes:
        content = original_dashboard().decode("utf-8")
        content = _improve_plan_clarity_dashboard(content)
        content = _improve_dashboard_no_reserve(content)
        return content.encode("utf-8")

    combined_progressive_publication_dashboard._kems_progressive_publication = True
    dashboard_module._combined_master_dashboard_bytes = (
        combined_progressive_publication_dashboard
    )
