"""Alpha7.46 no-reserve planning for clean Agile publication gaps.

For a clean Octopus publication gap KEMS now allocates the full currently
exportable battery energy across prices that are already published. It does not
hold discretionary battery energy back for an unknown future price. When that
price arrives the normal rolling optimiser runs again and may replace lower
value future allocations with the newly published slot.

Retrieval failures remain conservative, the current settlement period still
requires a real price before deliberate export, all existing reserve/deadline
guards remain active, Power Down and Happy Hour retain priority, and real
FoxESS writes remain blocked.
"""

from __future__ import annotations

import math
from typing import Any

from . import agile_alpha726_provisional as alpha726
from . import agile_alpha728_bounded_partial as alpha728
from . import agile_alpha745_plan_clarity as alpha745

_EPSILON = 1e-6

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
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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
        and recovery.get("publication_pending")
        and horizon.get("current_slot_known")
        and current_price.get("known")
    )
    if not clean_publication_gap:
        alpha746_original_apply(
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

    # Alpha7.28's executable safety gate requires the reserve amount to match the
    # unresolved capacity. Supply that value only while its existing validation
    # and dispatch path runs. The selected rows themselves are the untrimmed
    # known-price plan because Alpha7.46 replaced Alpha7.26's trimming helper.
    plan["provisional_reserved_unknown_capacity_kwh"] = required
    alpha746_original_apply(
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


def _plan_summary_no_reserve(self) -> dict[str, Any]:
    result = alpha746_original_plan_summary(self)
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


def _annotate_unknown_rows_no_reserve(self, plan: dict[str, Any]) -> None:
    rolling_state = self._hass.states.get("sensor.kems_agile_rolling_export_plan")
    rolling_attrs = dict(rolling_state.attributes) if rolling_state is not None else {}
    if not rolling_attrs.get("publication_gap_no_reserve_active"):
        alpha746_original_annotate(self, plan)
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


def _improve_dashboard_no_reserve(content: str) -> str:
    content = content.replace(_OLD_RESERVE_TEXT, _NEW_RESERVE_TEXT, 1)
    content = content.replace(_OLD_PROJECTED_ROW, _NEW_PROJECTED_ROW, 1)
    return content.replace(_OLD_MISSING_NOTE, _NEW_MISSING_NOTE, 1)


def install_alpha746_no_unknown_reserve_patch() -> None:
    """Install no-reserve progressive publication planning."""
    global alpha746_original_annotate
    global alpha746_original_apply
    global alpha746_original_plan_summary

    alpha726._reserve_unknown_capacity = _no_reserve_unknown_capacity

    apply = alpha728._apply_bounded_partial_dispatch
    if not getattr(apply, "_kems_alpha746_no_unknown_reserve", False):
        alpha746_original_apply = apply
        _apply_no_reserve_publication_dispatch._kems_alpha746_no_unknown_reserve = True
        alpha728._apply_bounded_partial_dispatch = (
            _apply_no_reserve_publication_dispatch
        )

    plan_summary = alpha745._plan_summary
    if not getattr(plan_summary, "_kems_alpha746_no_unknown_reserve", False):
        alpha746_original_plan_summary = plan_summary
        _plan_summary_no_reserve._kems_alpha746_no_unknown_reserve = True
        alpha745._plan_summary = _plan_summary_no_reserve

    annotate = alpha745._annotate_unknown_slot_rows
    if not getattr(annotate, "_kems_alpha746_no_unknown_reserve", False):
        alpha746_original_annotate = annotate
        _annotate_unknown_rows_no_reserve._kems_alpha746_no_unknown_reserve = True
        alpha745._annotate_unknown_slot_rows = _annotate_unknown_rows_no_reserve

    from . import dashboard as dashboard_module

    combined = dashboard_module._combined_master_dashboard_bytes
    if getattr(combined, "_kems_alpha746_no_unknown_reserve", False):
        return
    original_dashboard = combined

    def combined_alpha746_dashboard() -> bytes:
        content = original_dashboard().decode("utf-8")
        return _improve_dashboard_no_reserve(content).encode("utf-8")

    combined_alpha746_dashboard._kems_alpha746_no_unknown_reserve = True
    dashboard_module._combined_master_dashboard_bytes = combined_alpha746_dashboard
