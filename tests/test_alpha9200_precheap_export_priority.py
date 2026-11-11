"""Alpha9.200: forecast paid export stops at 15%; house may reach 10%."""

from __future__ import annotations

import ast
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from kems_core.discharge_slot_ledger import allocate_total_discharge_slots
from kems_core.forecast_path_scheduler import allocate_forecast_path_exports

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


def _slot(start: datetime, rate: float) -> dict[str, object]:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "rate_pence": rate,
    }


def _segments(now: datetime, count: int) -> list[dict[str, object]]:
    return [
        {
            "start": (now + timedelta(minutes=5 * n)).isoformat(),
            "end": (now + timedelta(minutes=5 * (n + 1))).isoformat(),
            "solar_kw": 0.0,
            "battery_kw": 7.0,
        }
        for n in range(count)
    ]


def _forecast(
    now: datetime,
    *,
    soc: float,
    house_kw: float,
    rates: list[float],
    export_floor: float | None,
):
    return allocate_forecast_path_exports(
        slots=[_slot(now + timedelta(minutes=30 * i), rate) for i, rate in enumerate(rates)],
        capacity_segments=_segments(now, len(rates) * 6),
        now=now,
        deadline=now + timedelta(minutes=30 * len(rates)),
        battery_capacity_kwh=56.42,
        soc_percent=soc,
        target_soc_percent=10.0,
        deliberate_export_floor_soc_percent=export_floor,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        max_charge_kw=7.0,
        house_kw=house_kw,
        export_limit_kw=7.0,
        minimum_export_rate_pence=6.6,
    )


def test_actual_2256_lower_bound_cannot_plan_2300_paid_export() -> None:
    now = datetime(2026, 11, 11, 22, 30, tzinfo=UTC)
    old = _forecast(now, soc=14.465, house_kw=1.316, rates=[8.0, 25.0], export_floor=None)
    fixed = _forecast(now, soc=14.465, house_kw=1.316, rates=[8.0, 25.0], export_floor=15.0)
    assert old.available and old.planned_battery_export_kwh > 1.0
    assert fixed.available
    assert fixed.planned_battery_export_kwh == pytest.approx(0.0)
    assert fixed.planned_house_battery_kwh > 1.0
    assert fixed.ending_soc_percent >= 10.0
    assert all(item.planned_battery_export_kwh == 0.0 for item in fixed.allocations)


def test_higher_price_2300_cannot_borrow_15_to_10_house_band() -> None:
    now = datetime(2026, 11, 11, 22, 30, tzinfo=UTC)
    fixed = _forecast(now, soc=16.0, house_kw=1.5, rates=[4.0, 25.0], export_floor=15.0)
    assert fixed.available
    assert fixed.planned_house_battery_kwh > 1.0
    assert fixed.allocations[1].planned_battery_export_kwh == 0.0
    assert fixed.ending_soc_percent >= 10.0


def test_legacy_forecast_callers_keep_single_target_floor() -> None:
    now = datetime(2026, 11, 11, 22, 30, tzinfo=UTC)
    default = _forecast(now, soc=16.0, house_kw=0.0, rates=[8.0, 25.0], export_floor=None)
    same = _forecast(now, soc=16.0, house_kw=0.0, rates=[8.0, 25.0], export_floor=10.0)
    assert default.planned_battery_export_kwh == pytest.approx(
        same.planned_battery_export_kwh
    )


def test_verified_physical_cap_prevents_total_ledger_export_below_15() -> None:
    now = datetime(2026, 11, 11, 22, 30, tzinfo=UTC)
    kwargs = {
        "slots": [_slot(now, 8.0), _slot(now + timedelta(minutes=30), 25.0)],
        "capacity_segments": _segments(now, 12),
        "now": now,
        "deadline": now + timedelta(hours=1),
        "required_discharge_kwh": 2.4,
        "house_kw": 1.316,
        "export_limit_kw": 7.0,
    }
    old = allocate_total_discharge_slots(**kwargs)
    limited = allocate_total_discharge_slots(**kwargs, maximum_paid_export_kwh=0.0)
    assert old.planned_battery_export_kwh > 0.0
    assert limited.planned_battery_export_kwh == 0.0
    assert limited.planned_house_battery_kwh > 0.0
    assert limited.unallocated_total_discharge_kwh > 0.0
    partial = allocate_total_discharge_slots(**kwargs, maximum_paid_export_kwh=0.25)
    assert 0.0 <= partial.planned_battery_export_kwh <= 0.25 + 1e-6


def _clarifier():
    """Load reporting-only functions in isolation from Home Assistant."""
    path = ROOT / "agile_observability_clarity.py"
    source = ast.parse(path.read_text(encoding="utf-8"))
    needed = {
        "_number",
        "_percent_text",
        "_house_bridge_action",
        "_clarify_policy_action_labels",
    }
    functions = [
        node
        for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name in needed
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "math": math,
        "_EPSILON": 1e-6,
        "PLANNING_TARGET_SOC_PERCENT": 15.0,
        "HARD_SAFETY_FLOOR_SOC_PERCENT": 10.0,
        "HARD_SAFETY_RECOVERY_SOC_PERCENT": 12.0,
    }
    tree = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    exec(compile(tree, path.as_posix(), "exec"), namespace)
    return namespace["_clarify_policy_action_labels"]


@pytest.mark.parametrize(
    ("mode", "action"),
    [
        ("cheap_charge", "cheap overnight period — import / charge; battery export blocked"),
        ("happy_hour_charge", "Happy Hour — grid priority / battery charge"),
        ("power_down_session", "Power Down — priority session"),
    ],
)
def test_priority_action_overrides_stale_house_bridge(mode: str, action: str) -> None:
    state: dict[str, Any] = {
        "current_action": "15% deliberate-export target reached — house-only",
        "today_action": "15% deliberate-export target reached — house-only",
        "rolling_export_plan": {
            "target_soc_percent": 15.0,
            "simulated_soc_percent": 14.0,
            "current_house_battery_kw": 1.0,
            "current_battery_export_target_kw": 0.0,
            "planning_target_reached": True,
            "dispatch_action": "stale house-only bridge",
        },
        "current_routing_snapshot": {
            "dispatch_mode": mode,
            "routing_action": action,
            "battery_to_home_kw": 0.0,
            "battery_export_kw": 0.0,
        },
    }
    proof = _clarifier()(state)
    assert state["current_action"] == action
    assert state["today_action"] == action
    assert state["rolling_export_plan"]["dispatch_action"] == action
    assert proof["priority_dispatch_mode"] == mode
    assert proof["hardware_writes"] == "blocked"


def test_ordinary_noncheap_house_bridge_remains_available() -> None:
    state: dict[str, Any] = {
        "rolling_export_plan": {
            "target_soc_percent": 15.0,
            "simulated_soc_percent": 14.0,
            "current_house_battery_kw": 1.0,
            "current_battery_export_target_kw": 0.0,
            "planning_target_reached": True,
        },
        "current_routing_snapshot": {
            "dispatch_mode": "price_optimised",
            "routing_action": "house first",
            "battery_to_home_kw": 1.0,
            "battery_export_kw": 0.0,
        },
    }
    _clarifier()(state)
    assert "house-only battery bridge toward 10%" in state["current_action"]
    assert state["rolling_export_plan"]["dispatch_action"] == state["current_action"]


def test_final_physical_command_guard_and_cheap_boundary_are_untouched() -> None:
    wrapper = (ROOT / "agile_forecast_path_scheduler.py").read_text(encoding="utf-8")
    ledger = (ROOT / "agile_total_discharge_ledger.py").read_text(encoding="utf-8")
    final = (ROOT / "agile_deadline_dominance.py").read_text(encoding="utf-8")
    assert "deliberate_export_floor_soc_percent=export_target" in wrapper
    assert "maximum_paid_export_kwh=paid_export_cap" in ledger
    assert '"physical_export_cap_still_required": True' in wrapper
    assert "_enforce_cheap_boundary(state, deadline)" in wrapper
    assert "return cap_physical_ac_export(state, resolved, now=now)" in final
