"""Read-only comparison of Agile rolling projection and physical reserve.

Do not use this advisory ledger as dispatch authority; the independent
physical reserve guard and all FoxESS commissioning gates remain authoritative.
"""

from __future__ import annotations

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

    gap = max(planned - guarded, 0.0)
    return {
        **result,
        "status": "physical_guard_tighter" if gap > 0.05 else "aligned",
        "source": "same_scan_verified_physical_lower_bound",
        "generated_at": plan["generated_at"],
        "planned_battery_export_kwh": round(planned, 3),
        "guard_exportable_physical_energy_kwh": round(guarded, 3),
        "plan_above_physical_budget_kwh": round(gap, 3),
        "planner_protected_house_energy_kwh": round(planner_house, 3),
        "guard_protected_home_energy_kwh": round(guard_house, 3),
        "extra_guard_house_protection_kwh": round(
            max(guard_house - planner_house, 0.0), 3
        ),
        "current_permitted_export_kw": physical_reserve.get(
            "permitted_export_kw"
        ),
        "physical_guard_status": physical_reserve.get("status"),
        "note": (
            "Full-window plan energy is advisory; the instantaneous FoxESS "
            "export write still passes an independent physical SOC, house "
            "and DNO guard on each scan."
        ),
    }
