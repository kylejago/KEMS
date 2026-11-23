"""Final physical AC export allowance for price-ranked Agile dispatch.

Preserves the independent FoxESS command guard and protected home reserve.
The 15% SOC arrival target is aspirational, never an export entitlement.
"""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any


def _num(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(number, 0.0) if isfinite(number) else 0.0


def _time(value: object) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return value.astimezone(UTC) if value.tzinfo else None


def reconcile_guarded_arrival_soc(
    plan: dict[str, Any], *, final_export_ac_kwh: float
) -> dict[str, Any]:
    """Read-only conditional SOC forecast *after* the verified physical cap.

    The forecast-path scheduler's 10% endpoint represents its uncapped
    theoretical discharge path. It is not evidence that the final protected
    export allocation will reach that value. Do not change any dispatch
    target, original forecast or controller authority here.
    """
    result: dict[str, Any] = {
        "status": "unavailable",
        "reporting_only": True,
        "hardware_writes": "forbidden",
        "dispatch_authority": "unchanged",
        "theoretical_model_ending_soc_percent": None,
        "guarded_conditional_ending_soc_percent": None,
    }
    path = plan.get("forecast_path_scheduler")
    proof = plan.get("physical_planning_evidence")
    budget = plan.get("physical_house_budget_evidence")
    if (
        not isinstance(path, dict)
        or not path.get("available")
        or not isinstance(proof, dict)
        or not proof.get("available")
        or not isinstance(budget, dict)
        or not budget.get("available")
    ):
        result["reason"] = "same_scan_physical_planning_or_path_unavailable"
        return result

    # No-solar model only: the path scheduler has not established a
    # chronological reconciliation when stored future solar is nonzero.
    if _num(path.get("forecast_solar_stored_kwh")) > 1e-6:
        result["reason"] = "solar_chronology_requires_full_path_replay"
        return result

    soc = _num(plan.get("planning_soc_percent"))
    physical_energy = _num(proof.get("physical_energy_lower_bound_kwh"))
    exported_stored = _num(budget.get("exportable_stored_kwh"))
    exported_ac = _num(budget.get("exportable_ac_kwh"))
    house_ac = _num(plan.get("predicted_house_battery_discharge_kwh"))
    theoretical_export_ac = _num(path.get("planned_battery_export_kwh"))
    if (
        soc <= 0.0
        or physical_energy <= 0.0
        or exported_stored <= 0.0
        or exported_ac <= 0.0
    ):
        result["reason"] = "no_verified_capacity_or_efficiency_basis"
        return result
    capacity_kwh = physical_energy / (soc / 100.0)
    discharge_efficiency = exported_ac / exported_stored
    if not (
        isfinite(capacity_kwh)
        and 0 < capacity_kwh <= 300
        and 0 < discharge_efficiency <= 1.0
    ):
        result["reason"] = "invalid_physical_capacity_or_efficiency"
        return result

    guarded_ac = min(_num(final_export_ac_kwh), exported_ac)
    stored_discharge = (house_ac + guarded_ac) / discharge_efficiency
    unbounded_soc = soc - 100.0 * stored_discharge / capacity_kwh
    floor = max(_num(plan.get("household_hard_floor_soc_percent")), 10.0)
    projected = max(floor, min(unbounded_soc, 100.0))
    theoretical_soc = _num(path.get("ending_soc_percent"))
    result.update(
        {
            "status": "guarded_physical_budget_projection",
            "basis": (
                "verified physical planning SOC less forecast house AC discharge "
                "and final guarded export AC; no future solar credited"
            ),
            "theoretical_model_ending_soc_percent": round(theoretical_soc, 3),
            "guarded_conditional_ending_soc_percent": round(projected, 3),
            "physical_planning_soc_percent": round(soc, 3),
            "forecast_house_battery_ac_kwh": round(house_ac, 3),
            "theoretical_model_battery_export_ac_kwh": round(
                theoretical_export_ac, 3
            ),
            "guarded_battery_export_ac_kwh": round(guarded_ac, 3),
            "theoretical_export_above_guarded_budget_ac_kwh": round(
                max(theoretical_export_ac - guarded_ac, 0.0), 3
            ),
            "capacity_kwh": round(capacity_kwh, 3),
            "discharge_efficiency": round(discharge_efficiency, 5),
            "arrival_guaranteed": False,
            "note": (
                "A conditional remaining-day house-demand projection, not a "
                "guaranteed arrival SOC or an instruction to discharge to 10%. "
                "The independent 15% deliberate-export/10% home floor still wins."
            ),
        }
    )
    return result

def cap_physical_ac_export(
    state: dict[str, Any], plan: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    """Limit final paid export, after all ledger, path and deadline planners."""
    proof = plan.get("physical_planning_evidence")
    evidence = plan.get("physical_house_budget_evidence")
    rows = plan.get("selected_slots")
    if (
        not plan.get("available")
        or not isinstance(proof, dict)
        or not proof.get("available")
        or not isinstance(evidence, dict)
        or not evidence.get("available")
        or not isinstance(rows, list)
    ):
        return plan

    # No verified budget means no intentional export. The independent guard
    # continues to own the physical hardware floor.
    ac = _num(evidence.get("exportable_ac_kwh"))
    ranked = sorted(
        (row for row in rows if isinstance(row, dict)),
        key=lambda row: (
            -_num(row.get("rate_pence")),
            _time(row.get("valid_from")) or now.astimezone(UTC),
        ),
    )
    remaining = ac
    grants = {}
    for row in ranked:
        start = _time(row.get("valid_from"))
        end = _time(row.get("valid_to"))
        if start is None or end is None or end <= now.astimezone(UTC):
            continue
        amount = min(_num(row.get("planned_battery_export_kwh")), remaining)
        grants[start] = round(amount, 3)
        remaining = max(remaining - amount, 0.0)

    selected = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start = _time(row.get("valid_from"))
        grant = grants.get(start, 0.0)
        if grant <= 0:
            continue
        updated = dict(row)
        updated["planned_battery_export_kwh"] = grant
        house = _num(updated.get("planned_battery_to_home_kwh"))
        updated["planned_total_battery_discharge_kwh"] = round(house + grant, 3)
        selected.append(updated)
    selected.sort(key=lambda row: _time(row.get("valid_from")) or now.astimezone(UTC))

    for group in (plan.get("total_discharge_selected_slots"), state.get("today_slots")):
        if not isinstance(group, list):
            continue
        for row in group:
            if not isinstance(row, dict):
                continue
            start = _time(row.get("valid_from"))
            if start not in grants:
                continue
            grant = grants[start]
            house = _num(row.get("planned_battery_to_home_kwh"))
            row["planned_total_battery_discharge_kwh"] = round(house + grant, 3)
            row["planned_battery_export_kwh"] = grant
            if group is state.get("today_slots"):
                row["rolling_planned_battery_export_kwh"] = grant
                row["battery_export_kwh"] = grant
                if grant <= 0:
                    row["rolling_action"] = "house first — physical export budget"
                    row["actions"] = [row["rolling_action"]]

    current = now.astimezone(UTC)
    active = next(
        (
            row
            for row in selected
            if (_time(row.get("valid_from")) or current)
            <= current
            < (_time(row.get("valid_to")) or current)
        ),
        None,
    )
    export_kw = 0.0
    if active:
        end = _time(active.get("valid_to"))
        hours = max((end - current).total_seconds() / 3600, 1e-6)
        export_kw = min(
            _num(plan.get("current_battery_export_target_kw")),
            _num(active.get("planned_battery_export_kwh")) / hours,
        )

    total = round(sum(_num(row["planned_battery_export_kwh"]) for row in selected), 3)
    original = _num(plan.get("planned_battery_export_kwh"))
    house_kw = _num(plan.get("current_house_battery_kw"))
    plan.update(
        {
            "selected_slots": selected,
            "next_export_slot": next(
                (
                    dict(row)
                    for row in selected
                    if (_time(row.get("valid_to")) or current) > current
                ),
                None,
            ),
            "planned_battery_export_kwh": total,
            "exportable_battery_energy_kwh": total,
            "current_battery_export_target_kw": round(export_kw, 3),
            "current_battery_discharge_target_kw": round(house_kw + export_kw, 3),
            "physical_ac_export_budget_applied": True,
            "physical_ac_export_budget_kwh": round(ac, 3),
            "physical_ac_export_budget_removed_kwh": round(max(original - total, 0), 3),
        }
    )
    house_total = plan.get("predicted_house_battery_discharge_kwh")
    if house_total is not None:
        plan["planned_total_battery_discharge_kwh"] = round(
            _num(house_total) + total, 3
        )
    # This must be the last projection: all physical AC export cuts are final.
    projection = reconcile_guarded_arrival_soc(
        plan, final_export_ac_kwh=total
    )
    plan["forecast_path_budget_reconciliation"] = projection
    plan["forecast_path_reconciled_ending_soc_percent"] = (
        projection.get("guarded_conditional_ending_soc_percent")
    )
    plan["forecast_path_theoretical_ending_soc_percent"] = (
        projection.get("theoretical_model_ending_soc_percent")
    )
    return plan
