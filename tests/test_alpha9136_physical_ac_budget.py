"""Alpha9.136 pure scheduling regressions: conservative physical AC energy."""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
spec = importlib.util.spec_from_file_location(
    "kems_alpha9136_physical_ac", ROOT / "agile_physical_export_budget.py"
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _slot(hour, rate, export):
    return {
        "valid_from": f"2026-10-24T{hour}:00+01:00",
        "valid_to": f"2026-10-24T{hour}:30+01:00",
        "rate_pence": rate,
        "planned_battery_to_home_kwh": 0.45,
        "planned_battery_export_kwh": export,
    }


def _case(budget=8.491):
    rows = [
        _slot("17", 16.34, 1.172),
        _slot("18", 16.48, 3.016),
        _slot("19", 8.73, 3.016),
        _slot("20", 7.69, 0.075),
    ]
    rows[1]["valid_from"] = "2026-10-24T17:30:00+01:00"
    rows[1]["valid_to"] = "2026-10-24T18:00:00+01:00"
    rows.extend(
        [
        {
            "valid_from": "2026-10-24T17:45:00+01:00",
            "valid_to": "2026-10-24T18:15:00+01:00",
            "rate_pence": 16.94,
            "planned_battery_to_home_kwh": 0.45,
            "planned_battery_export_kwh": 3.016,
        },
        {
            "valid_from": "2026-10-24T18:15:00+01:00",
            "valid_to": "2026-10-24T18:45:00+01:00",
            "rate_pence": 16.61,
            "planned_battery_to_home_kwh": 0.45,
            "planned_battery_export_kwh": 3.016,
        },
        ]
    )
    p = {
        "available": True,
        "physical_planning_evidence": {"available": True},
        "physical_house_budget_evidence": {
            "available": True,
            "exportable_stored_kwh": 8.938,
            "exportable_ac_kwh": budget,
        },
        "selected_slots": rows,
        "total_discharge_selected_slots": [dict(row) for row in rows],
        "planned_battery_export_kwh": sum(
            row["planned_battery_export_kwh"] for row in rows
        ),
        "current_house_battery_kw": 0.88,
        "current_battery_export_target_kw": 5.984,
        "current_battery_discharge_target_kw": 6.864,
        "predicted_house_battery_discharge_kwh": 5.935,
    }
    return p, {"today_slots": [dict(row) for row in rows]}


def test_caps_total_and_keeps_best_prices_before_lower_slots():
    plan, state = _case()
    result = mod.cap_physical_ac_export(
        state, plan, now=datetime.fromisoformat("2026-10-24T17:18:20+01:00")
    )
    assert result["physical_ac_export_budget_applied"]
    assert result["planned_battery_export_kwh"] <= 8.491
    assert result["physical_ac_export_budget_removed_kwh"] > 4
    by_rate = {
        row["rate_pence"]: row["planned_battery_export_kwh"]
        for row in result["selected_slots"]
    }
    assert by_rate[16.94] == 3.016
    assert by_rate[16.61] == 3.016
    assert 16.34 not in by_rate
    assert 8.73 not in by_rate
    assert 7.69 not in by_rate
    assert result["current_battery_export_target_kw"] == 0
    assert result["current_battery_discharge_target_kw"] == 0.88
    assert all(
        row["rolling_planned_battery_export_kwh"] == 0
        for row in state["today_slots"]
        if row["rate_pence"] == 8.73
    )


def test_target_never_increases_export_and_home_remains():
    plan, state = _case(budget=2.5)
    before = {
        row["valid_from"]: row["planned_battery_export_kwh"]
        for row in plan["selected_slots"]
    }
    result = mod.cap_physical_ac_export(
        state, plan, now=datetime.fromisoformat("2026-10-24T17:50:00+01:00")
    )
    assert result["planned_battery_export_kwh"] <= 2.5
    assert 0 <= result["current_battery_export_target_kw"] <= 5.984
    assert result["current_battery_discharge_target_kw"] >= 0.88
    for row in result["selected_slots"]:
        assert row["planned_battery_export_kwh"] <= before[row["valid_from"]]


def test_no_physical_proof_does_not_modify_digital_twin():
    plan, state = _case()
    plan["physical_planning_evidence"]["available"] = False
    initial = dict(plan)
    result = mod.cap_physical_ac_export(
        state, plan, now=datetime.fromisoformat("2026-10-24T17:18:20+01:00")
    )
    assert result == initial


def test_zero_budget_blocks_paid_export_but_not_house():
    plan, state = _case(budget=0.0)
    result = mod.cap_physical_ac_export(
        state, plan, now=datetime.fromisoformat("2026-10-24T17:18:20+01:00")
    )
    assert result["selected_slots"] == []
    assert result["current_battery_export_target_kw"] == 0
    assert result["current_battery_discharge_target_kw"] == 0.88


def test_dst_slots_are_distinct_physical_instants():
    now = datetime.fromisoformat("2026-10-25T00:45:00+01:00")
    first = {
        "valid_from": "2026-10-25T01:00:00+01:00",
        "valid_to": "2026-10-25T01:30:00+01:00",
        "rate_pence": 8,
        "planned_battery_export_kwh": 1,
    }
    second = {
        "valid_from": "2026-10-25T01:00:00+00:00",
        "valid_to": "2026-10-25T01:30:00+00:00",
        "rate_pence": 9,
        "planned_battery_export_kwh": 1,
    }
    plan = {
        "available": True,
        "physical_planning_evidence": {"available": True},
        "physical_house_budget_evidence": {
            "available": True,
            "exportable_ac_kwh": 1.0,
        },
        "selected_slots": [first, second],
        "current_house_battery_kw": 0.3,
        "current_battery_export_target_kw": 0,
        "planned_battery_export_kwh": 2,
    }
    result = mod.cap_physical_ac_export({"today_slots": []}, plan, now=now)
    assert len(result["selected_slots"]) == 1
    assert result["selected_slots"][0]["valid_from"].endswith("+00:00")


def test_budget_contract_executes_after_deadline_priority():
    source = (ROOT / "agile_deadline_dominance.py").read_text()
    assert "return cap_physical_ac_export(state, resolved, now=now)" in source


def test_real_guard_stored_kwh_converts_to_ac_before_reconciliation():
    from kems_core.agile_plan_budget_reconciliation import reconcile_agile_budget

    at = "2026-10-24T17:18:20+01:00"
    state = {
        "rolling_export_plan": {
            "available": True,
            "generated_at": at,
            "physical_planning_evidence": {"available": True},
            "physical_house_budget_evidence": {
                "available": True,
                "exportable_stored_kwh": 8.938,
                "exportable_ac_kwh": 8.491,
            },
            "planned_battery_export_kwh": 8.491,
            "protected_house_energy_kwh": 10.763,
            "current_battery_export_target_kw": 0.0,
            "required_in_current_slot_kwh": 0.0,
            "selected_slots": [],
        }
    }
    physical = {
        "physical_energy_evidence": {"observed_at": at},
        "exportable_physical_energy_kwh": 8.937,
        "protected_home_energy_kwh": 11.329,
    }
    result = reconcile_agile_budget(state, physical)
    assert result["status"] == "aligned"
    assert result["comparison_units"] == "AC_kWh"
    assert 8.48 < result["guard_exportable_ac_energy_kwh"] < 8.50
    assert result["plan_above_physical_budget_kwh"] < 0.01
