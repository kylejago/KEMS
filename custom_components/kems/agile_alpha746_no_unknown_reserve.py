"""Alpha7.46 no-reserve planning for clean Agile publication gaps.

When Octopus has successfully published most of the current local-day Agile
prices but one or more future settlement periods are still unpublished, KEMS
must not hold battery energy back merely in case those unknown prices prove
better later.

For a clean publication gap Alpha7.46 therefore plans the full currently
exportable battery energy across the best *known* prices before the next cheap
period. The unknown slot keeps no discretionary battery reservation. As soon as
Octopus publishes that price the normal rolling planner runs again and may move
energy from lower-value future slots into the newly published slot.

Retrieval failures remain conservative, the active settlement period still
requires a real price before deliberate export, Alpha7.34/7.40 deadline and
opportunity guards remain intact, Power Down and Happy Hour retain priority,
and real FoxESS writes remain blocked.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_alpha717_dispatch as alpha717
from . import agile_alpha725_nonzero as alpha725
from . import agile_alpha728_bounded_partial as alpha728
from . import agile_alpha745_plan_clarity as alpha745
from . import agile_rolling_replan as rolling
from . import agile_smart_export as agile
from .kems_core import SimulationConfig
from .tariff import TariffSettings

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


def _dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _known_price_plan(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> list[dict[str, Any]]:
    """Allocate all exportable energy across only the currently known prices."""
    now_utc = now.astimezone(UTC)
    deadline = agile._next_cheap(now, tariff).astimezone(UTC)
    effective_kw = max(_number(plan.get("effective_discharge_kw")) or 0.0, 0.0)
    exportable = max(
        _number(plan.get("exportable_battery_energy_kwh")) or 0.0,
        0.0,
    )
    current_house_kw = rolling._current_house_headroom_kw(self, config)

    candidates: list[dict[str, Any]] = []
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        start = _dt(slot.get("valid_from"))
        end = _dt(slot.get("valid_to"))
        rate = _number(slot.get("rate_pence"))
        if start is None or end is None or rate is None:
            continue
        overlap_start = max(start, now_utc)
        overlap_end = min(end, deadline)
        if overlap_end <= overlap_start:
            continue
        is_current = start <= now_utc < end
        available_kw = effective_kw
        if is_current:
            available_kw = max(available_kw - current_house_kw, 0.0)
        hours = (overlap_end - overlap_start).total_seconds() / 3600.0
        candidates.append(
            {
                "slot": slot,
                "start": start,
                "rate": rate,
                "capacity_kwh": max(available_kw * hours, 0.0),
                "is_current": is_current,
                "allocation_kwh": 0.0,
            }
        )

    total_capacity = sum(item["capacity_kwh"] for item in candidates)
    desired = min(exportable, total_capacity)
    current = next((item for item in candidates if item["is_current"]), None)
    current_capacity = current["capacity_kwh"] if current is not None else 0.0
    safety_headroom = min(
        effective_kw * rolling.SAFETY_HEADROOM_MINUTES / 60.0,
        total_capacity,
    )
    required_now = max(
        desired + safety_headroom - max(total_capacity - current_capacity, 0.0),
        0.0,
    )
    if current is not None and desired > _EPSILON:
        current["allocation_kwh"] = min(required_now, current_capacity, desired)

    remaining = max(
        desired - sum(item["allocation_kwh"] for item in candidates),
        0.0,
    )
    for item in sorted(candidates, key=lambda value: value["rate"], reverse=True):
        if remaining <= _EPSILON:
            break
        spare = max(item["capacity_kwh"] - item["allocation_kwh"], 0.0)
        allocated = min(remaining, spare)
        item["allocation_kwh"] += allocated
        remaining -= allocated

    selected: list[dict[str, Any]] = []
    for item in sorted(candidates, key=lambda value: value["start"]):
        allocation = round(float(item["allocation_kwh"]), 3)
        if allocation <= _EPSILON:
            continue
        slot = item["slot"]
        selected.append(
            {
                "valid_from": slot.get("valid_from"),
                "label": slot.get("label"),
                "rate_pence": round(float(item["rate"]), 5),
                "planned_battery_export_kwh": allocation,
                "deadline_forced": bool(
                    item["is_current"] and required_now > _EPSILON
                ),
                "publication_gap_no_reserve": True,
            }
        )
    return selected


def _apply_no_reserve_publication_dispatch(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> None:
    """Use all known-price capacity for clean publication gaps only."""
    horizon = state.get("planning_horizon")
    horizon = horizon if isinstance(horizon, dict) else {}
    recovery = alpha728._recovery_evidence(self, horizon)
    publication_pending = bool(
        recovery.get("verified") and recovery.get("publication_pending")
    )
    if not publication_pending:
        alpha746_original_apply(
            self,
            state,
            plan,
            now=now,
            config=config,
            tariff=tariff,
        )
        return

    was_held = bool(plan.get("price_horizon_battery_export_held"))
    provisional_active = bool(plan.get("provisional_plan_active"))
    current_known = bool(horizon.get("current_slot_known"))
    current_price = alpha728._current_price_evidence(state, now)
    eligible = bool(
        was_held
        and provisional_active
        and current_known
        and current_price.get("known")
    )
    if not eligible:
        alpha746_original_apply(
            self,
            state,
            plan,
            now=now,
            config=config,
            tariff=tariff,
        )
        return

    selected_full = _known_price_plan(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )
    plan["provisional_selected_slots"] = selected_full
    plan["provisional_planned_battery_export_kwh"] = round(
        sum(float(item["planned_battery_export_kwh"]) for item in selected_full),
        3,
    )
    plan["provisional_reserved_unknown_capacity_kwh"] = 0.0
    selected_map = {
        str(item.get("valid_from") or ""): dict(item) for item in selected_full
    }
    alpha728._restore_known_allocations(state, selected_map, now=now)

    targets = alpha717._dispatch_targets(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )
    export_target = max(
        _number(targets.get("battery_export_target_kw")) or 0.0,
        0.0,
    )
    discharge_target = max(
        _number(targets.get("battery_discharge_target_kw")) or 0.0,
        0.0,
    )
    house_target = max(_number(targets.get("house_battery_kw")) or 0.0, 0.0)
    selected = alpha728._executable_selected_slots(
        plan,
        state,
        now=now,
        export_target_kw=export_target,
    )
    planned = round(
        sum(
            max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
            for item in selected
        ),
        3,
    )
    exportable = max(
        _number(plan.get("exportable_battery_energy_kwh")) or 0.0,
        0.0,
    )

    if export_target > alpha725.NONZERO_EXPORT_THRESHOLD_KW:
        action = "progressive known-price export — unpublished slots not reserved"
    else:
        action = "progressive known-price hold — current known slot not selected"

    plan.update(
        {
            "bounded_partial_horizon_eligible": True,
            "bounded_partial_horizon_reason": (
                "clean Octopus publication gap; optimise all exportable energy "
                "across published prices and re-rank when new prices arrive"
            ),
            "bounded_upstream_gap_verified": True,
            "bounded_recovery_evidence": recovery,
            "bounded_current_price_known": True,
            "bounded_current_price": current_price,
            "bounded_unknown_capacity_required_kwh": 0.0,
            "bounded_unknown_capacity_reserved_kwh": 0.0,
            "bounded_unknown_capacity_sufficient": True,
            "bounded_unknown_slot_dispatch_blocked": True,
            "bounded_partial_horizon_dispatch_active": True,
            "publication_gap_no_reserve_active": True,
            "unknown_price_reservation_policy": "none",
            "economic_plan_status": "progressive_known_prices_no_reserve",
            "dispatch_blocked_for_price_horizon": False,
            "dispatch_permitted_battery_export_kw": round(export_target, 3),
            "dispatch_mode": "progressive_known_prices_no_reserve",
            "bounded_underlying_dispatch_mode": targets.get("mode"),
            "dispatch_action": action,
            "current_house_battery_kw": round(house_target, 3),
            "current_battery_discharge_target_kw": round(discharge_target, 3),
            "current_battery_export_target_kw": round(export_target, 3),
            "planned_battery_export_kwh": planned,
            "selected_slots": selected,
            "next_export_slot": alpha728._next_selected_slot(selected, now),
            "unallocated_exportable_kwh": round(max(exportable - planned, 0.0), 3),
            "price_horizon_battery_export_held": False,
            "price_horizon_status": "progressive_known_prices_no_reserve",
        }
    )
    horizon.update(
        {
            "battery_export_held": False,
            "status": "progressive_known_prices_no_reserve",
            "bounded_partial_dispatch": True,
            "upstream_gap_verified": True,
            "unknown_capacity_required_kwh": 0.0,
            "unknown_capacity_reserved_kwh": 0.0,
            "unknown_capacity_sufficient": True,
            "unknown_slot_dispatch_blocked": True,
            "unknown_price_reservation_policy": "none",
            "replan_when_price_publishes": True,
        }
    )
    state["planning_horizon"] = horizon
    state["current_action"] = action

    current_slot = alpha717._current_slot(state, now)
    if isinstance(current_slot, dict):
        remaining_hours = alpha717._remaining_current_slot_hours(state, now)
        current_slot["rolling_target_battery_export_kw"] = round(export_target, 3)
        current_slot["rolling_target_total_discharge_kw"] = round(
            discharge_target,
            3,
        )
        current_slot["rolling_planned_battery_export_kwh"] = round(
            export_target * remaining_hours,
            3,
        )
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
    coverage = (
        100.0
        if exportable <= 0.01
        else min(planned / exportable * 100.0, 100.0)
    )
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
    slot_state = self._hass.states.get("sensor.kems_agile_slot_decisions_today")
    if slot_state is None:
        return
    attrs = dict(slot_state.attributes)
    slots = [dict(item) for item in attrs.get("slots", []) if isinstance(item, dict)]
    for row in slots:
        decision = str(row.get("decision") or "")
        if decision.startswith("Waiting for Octopus price"):
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
    content = content.replace(_OLD_MISSING_NOTE, _NEW_MISSING_NOTE, 1)
    return content


def install_alpha746_no_unknown_reserve_patch() -> None:
    """Install no-reserve progressive publication planning."""
    global alpha746_original_apply
    global alpha746_original_plan_summary

    apply = alpha728._apply_bounded_partial_dispatch
    if not getattr(apply, "_kems_alpha746_no_unknown_reserve", False):
        alpha746_original_apply = apply
        _apply_no_reserve_publication_dispatch._kems_alpha746_no_unknown_reserve = True
        alpha728._apply_bounded_partial_dispatch = _apply_no_reserve_publication_dispatch

    plan_summary = alpha745._plan_summary
    if not getattr(plan_summary, "_kems_alpha746_no_unknown_reserve", False):
        alpha746_original_plan_summary = plan_summary
        _plan_summary_no_reserve._kems_alpha746_no_unknown_reserve = True
        alpha745._plan_summary = _plan_summary_no_reserve

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
