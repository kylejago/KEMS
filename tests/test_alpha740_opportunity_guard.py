import ast
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "custom_components" / "kems" / "agile_alpha740_opportunity_guard.py"


def _load_economic_guard():
    """Load the pure planning helpers without importing Home Assistant."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    function_names = {
        "_number",
        "_dt",
        "_current_slot",
        "_remaining_hours",
        "_economic_guard",
    }
    constant_names = {
        "_EPSILON",
        "PRICE_ADVANTAGE_PENCE",
        "UNCERTAINTY_MARGIN_FRACTION",
    }
    body: list[ast.stmt] = []
    for node in tree.body:
        constant = isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in constant_names
            for target in node.targets
        )
        helper = isinstance(node, ast.FunctionDef) and node.name in function_names
        if constant or helper:
            body.append(node)

    isolated = ast.Module(body=body, type_ignores=[])
    namespace = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "math": math,
    }
    exec(
        compile(ast.fix_missing_locations(isolated), str(MODULE), "exec"),
        namespace,
    )
    return namespace["_economic_guard"]


def _slot(start: datetime, rate: float) -> dict:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "rate_pence": rate,
    }


def test_current_better_slot_gets_proactive_export_floor() -> None:
    economic_guard = _load_economic_guard()
    now = datetime(2026, 8, 20, 14, 10, tzinfo=UTC)
    current = _slot(now.replace(minute=0), 12.27)
    future_a = _slot(now.replace(minute=30), 11.95)
    future_b = _slot(now.replace(hour=15, minute=0), 10.20)
    state = {"today_slots": [current, future_a, future_b]}
    plan = {
        "exportable_battery_energy_kwh": 4.0,
        "planned_battery_export_kwh": 4.0,
    }

    guard = economic_guard(state, plan, now=now, effective_kw=7.0)

    assert guard["active"] is True
    assert guard["current_rate_pence"] == 12.27
    assert guard["price_advantage_pence"] > 0
    assert guard["minimum_current_export_kwh"] > 0


def test_worse_current_slot_does_not_preempt_better_future_slots() -> None:
    economic_guard = _load_economic_guard()
    now = datetime(2026, 8, 20, 14, 10, tzinfo=UTC)
    current = _slot(now.replace(minute=0), 8.0)
    future_a = _slot(now.replace(minute=30), 12.0)
    future_b = _slot(now.replace(hour=15, minute=0), 11.0)
    state = {"today_slots": [current, future_a, future_b]}
    plan = {
        "exportable_battery_energy_kwh": 2.0,
        "planned_battery_export_kwh": 2.0,
    }

    guard = economic_guard(state, plan, now=now, effective_kw=7.0)

    assert guard["active"] is False
    assert guard["minimum_current_export_kwh"] == 0
