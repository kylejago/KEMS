"""Read-only comparison of Agile rolling projection and physical reserve.

Do not use this advisory ledger as dispatch authority; the independent
physical reserve guard and all FoxESS commissioning gates remain authoritative.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _current_slot_export_alignment(plan: dict[str, Any]) -> dict[str, Any]:
    """Spot a current export request not represented by selected Agile slots.

    Diagnostic only. Mandatory deadline discharge remains an explicit escape;
    no planning commands are modified by this comparison.
    """
    try:
        now = datetime.fromisoformat(str(plan["generated_at"]))
    except (KeyError, TypeError, ValueError):
        return {"status": "unknown", "reason": "missing_timestamp"}
    if now.tzinfo is None:
        return {"status": "unknown", "reason": "naive_timestamp"}
    selections = plan.get("selected_slots")
    if not isinstance(selections, list):
        return {"status": "unknown", "reason": "selected_slots_unavailable"}
    scheduled = 0.0
    for item in selections:
        if not isinstance(item, dict):
            continue
        try:
            begin = datetime.fromisoformat(str(item["valid_from"]))
            end = datetime.fromisoformat(str(item["valid_to"]))
        except (KeyError, ValueError, TypeError):
            continue
        if begin.tzinfo is None or end.tzinfo is None or not begin <= now < end:
            continue
        amount = _number(item.get("planned_battery_export_kwh"))
        if amount is not None and amount > 0:
            scheduled += amount
    requested = _number(plan.get("current_battery_export_target_kw"))
    forced = _number(plan.get("required_in_current_slot_kwh"))
    if requested is None or forced is None:
        return {"status": "unknown", "reason": "current_dispatch_not_available"}
    conflict = requested > 0.15 and scheduled <= 0.001 and forced <= 0.001
    return {
        "status": ("export_target_outside_selected_slot" if conflict else "consistent"),
        "current_requested_export_kw": round(max(requested, 0.0), 3),
        "selected_current_export_kwh": round(scheduled, 3),
        "required_deadline_current_kwh": round(max(forced, 0.0), 3),
        "source": "advisory_plan_internal_comparison",
        "hardware_writes": "blocked",
    }


def reconcile_agile_budget(
    state: dict[str, Any], physical_reserve: dict[str, Any]
) -> dict[str, Any]:
    """Show when the plan promises more export energy than the stricter guard."""
    result: dict[str, Any] = {
        "status": "unavailable",
        "scope": "diagnostics_only",
        "hardware_writes": "blocked",
        "dispatch_authority": "unchanged_independent_physical_guard",
    }
    plan = state.get("rolling_export_plan")
    if not isinstance(plan, dict) or not plan.get("available"):
        result["reason"] = "no_current_rolling_plan"
        return result
    proof = plan.get("physical_planning_evidence")
    guard_proof = physical_reserve.get("physical_energy_evidence")
    if not isinstance(proof, dict) or not proof.get("available"):
        result["reason"] = "rolling_plan_not_based_on_verified_physical_energy"
        return result
    if not isinstance(guard_proof, dict) or (
        plan.get("generated_at") != guard_proof.get("observed_at")
    ):
        result["reason"] = "planning_and_guard_not_from_same_scan"
        return result

    # When no deliberate export was requested, the real-time physical reserve
    # correctly returns before calculating an exportable stored-kWh budget.
    # Reporting "missing_or_invalid_energy_budget" in that idle state is a
    # false diagnostic alarm. Never fabricate an independently checked budget
    # or call a skipped safety guard "aligned".
    requested = _number(physical_reserve.get("requested_export_kw"))
    permitted = _number(physical_reserve.get("permitted_export_kw"))
    if (
        physical_reserve.get("status") == "no_deliberate_export_requested"
        and requested is not None
        and permitted is not None
        and 0.0 <= requested <= 0.001
        and 0.0 <= permitted <= 0.001
    ):
        planned_idle = _number(plan.get("planned_battery_export_kwh"))
        evidence_idle = plan.get("physical_house_budget_evidence")
        planned_ac = (
            _number(evidence_idle.get("exportable_ac_kwh"))
            if isinstance(evidence_idle, dict) and evidence_idle.get("available")
            else None
        )
        protected = (
            _number(evidence_idle.get("protected_house_stored_kwh"))
            if isinstance(evidence_idle, dict) and evidence_idle.get("available")
            else None
        )
        if (
            planned_idle is None
            or planned_ac is None
            or protected is None
            or min(planned_idle, planned_ac, protected) < 0
        ):
            result["reason"] = "idle_without_verified_planner_budget"
            return result
        return {
            **result,
            "status": "idle_no_export_requested",
            "reason": "independent_export_energy_guard_not_required_at_zero_request",
            "generated_at": plan.get("generated_at"),
            "planner_proposed_export_ac_kwh": round(planned_idle, 3),
            "planner_verified_ac_export_budget_kwh": round(planned_ac, 3),
            "planner_protected_house_stored_kwh": round(protected, 3),
            "guard_budget_evaluated": False,
            "guard_exportable_physical_energy_kwh": None,
            "current_permitted_export_kw": 0.0,
            "current_slot_dispatch_alignment": _current_slot_export_alignment(plan),
            "physical_guard_status": physical_reserve.get("status"),
            "note": (
                "Physical guard intentionally skipped export-energy calculations "
                "because no export was requested. Planner budget is advisory only."
            ),
        }

    planned = _number(plan.get("planned_battery_export_kwh"))
    guarded = _number(physical_reserve.get("exportable_physical_energy_kwh"))
    planner_house = _number(plan.get("protected_house_energy_kwh"))
    guard_house = _number(physical_reserve.get("protected_home_energy_kwh"))
    if (
        planned is None
        or guarded is None
        or min(planned, guarded) < 0
        or planner_house is None
        or guard_house is None
        or min(planner_house, guard_house) < 0
    ):
        result["reason"] = "missing_or_invalid_energy_budget"
        return result

    # The physical guard measures *stored* kWh. Selected Agile export slots
    # are delivered AC kWh. Alpha9.135 compared these unlike quantities.
    evidence = plan.get("physical_house_budget_evidence")
    stored = (
        _number(evidence.get("exportable_stored_kwh"))
        if isinstance(evidence, dict) and evidence.get("available")
        else None
    )
    ac = (
        _number(evidence.get("exportable_ac_kwh"))
        if isinstance(evidence, dict) and evidence.get("available")
        else None
    )
    conversion = (
        ac / stored if stored is not None and stored > 0 and ac is not None else None
    )
    guarded_ac = guarded * conversion if conversion is not None else None
    compared_guard = guarded_ac if guarded_ac is not None else guarded
    gap = max(planned - compared_guard, 0.0)
    return {
        **result,
        "status": "physical_guard_tighter" if gap > 0.05 else "aligned",
        "source": "same_scan_verified_physical_lower_bound",
        "comparison_units": (
            "AC_kWh" if guarded_ac is not None else "legacy_unconverted_kWh"
        ),
        "generated_at": plan["generated_at"],
        "planned_battery_export_kwh": round(planned, 3),
        "guard_exportable_physical_energy_kwh": round(guarded, 3),
        "guard_exportable_ac_energy_kwh": (
            round(guarded_ac, 3) if guarded_ac is not None else None
        ),
        "plan_above_physical_budget_kwh": round(gap, 3),
        "current_guard_limited_export_ceiling_kwh": round(
            min(planned, compared_guard), 3
        ),
        "current_guard_limited_ceiling_is_schedule": False,
        "current_slot_dispatch_alignment": _current_slot_export_alignment(plan),
        "planner_solar_house_credit_kwh": _number(
            plan.get("forecast_solar_to_house_credit_kwh")
        ),
        "guard_conservative_solar_credit_kwh": _number(
            physical_reserve.get("conservative_solar_credit_kwh")
        ),
        "planner_protected_house_energy_kwh": round(planner_house, 3),
        "guard_protected_home_energy_kwh": round(guard_house, 3),
        "extra_guard_house_protection_kwh": round(
            max(guard_house - planner_house, 0.0), 3
        ),
        "current_permitted_export_kw": physical_reserve.get("permitted_export_kw"),
        "physical_guard_status": physical_reserve.get("status"),
        "note": (
            "Full-window plan energy is advisory; the instantaneous FoxESS "
            "export write still passes an independent physical SOC, house "
            "and DNO guard on each scan."
        ),
    }
