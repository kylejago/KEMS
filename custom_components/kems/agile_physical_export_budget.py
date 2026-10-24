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


def cap_physical_ac_export(
    state: dict[str, Any], plan: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    """Limit final paid export, after all ledger, path and deadline planners."""
    proof = plan.get("physical_planning_evidence")
    evidence = plan.get("physical_house_budget_evidence")
    rows = plan.get("selected_slots")
    if (
        not plan.get("available")
        or not isinstance(proof, dict) or not proof.get("available")
        or not isinstance(evidence, dict) or not evidence.get("available")
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
            "physical_ac_export_budget_removed_kwh": round(
                max(original - total, 0), 3
            ),
        }
    )
    house_total = plan.get("predicted_house_battery_discharge_kwh")
    if house_total is not None:
        plan["planned_total_battery_discharge_kwh"] = round(
            _num(house_total) + total, 3
        )
    return plan
