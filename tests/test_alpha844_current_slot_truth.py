"""Regression coverage for Alpha8.44 active Agile slot truth reconciliation."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "custom_components" / "kems" / "agile_current_slot_truth.py"
COMPAT = ROOT / "custom_components" / "kems" / "agile_alpha7_compat.py"


def _reconciler():
    """Load the pure active-slot helper without importing Home Assistant."""
    tree = ast.parse(SOURCE.read_text())
    wanted = {"_number", "_datetime", "_reconcile_current_slot"}
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "_EPSILON": 1e-6,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, SOURCE.as_posix(), "exec"), namespace)
    return namespace["_reconcile_current_slot"]


def _state(*, export_kwh: float = 0.0) -> dict[str, Any]:
    return {
        "today_slots": [
            {
                "label": "22:00",
                "valid_from": "2026-08-28T21:00:00+00:00",
                "valid_to": "2026-08-28T21:30:00+00:00",
                "rate_pence": 14.2,
                "battery_export_kwh": 0.59,
                "rolling_planned_battery_export_kwh": export_kwh,
                "rolling_action": (
                    "planned battery export — rolling replan"
                    if export_kwh > 0
                    else "hold — re-evaluate next KEMS scan"
                ),
                "ending_soc_percent": 26.5,
                "actions": ["deadline export"],
            },
            {
                "label": "22:30",
                "valid_from": "2026-08-28T21:30:00+00:00",
                "valid_to": "2026-08-28T22:00:00+00:00",
                "battery_export_kwh": 0.0,
                "actions": ["house first — no battery export planned"],
            },
        ]
    }


def test_uploaded_2211_stale_deadline_export_is_removed_at_nine_percent() -> None:
    """A current 9% SOC cannot retain an old 0.59 kWh deadline-export row."""
    reconcile = _reconciler()
    state = _state(export_kwh=0.0)
    plan = {
        "available": True,
        "simulated_soc_percent": 9.0,
        "target_soc_percent": 10.0,
    }

    reconcile(
        state,
        plan,
        now=datetime(2026, 8, 28, 21, 11, tzinfo=UTC),
    )

    current = state["today_slots"][0]
    assert current["battery_export_kwh"] == 0.0
    assert current["actions"] == ["10% reserve floor — no battery discharge/export"]
    assert current["rolling_action"] == current["actions"][0]
    assert current["current_soc_percent"] == 9.0
    assert current["ending_soc_percent"] is None
    assert current["pre_replan_forecast_ending_soc_percent"] == 26.5
    assert current["current_slot_plan_reconciled"] is True


def test_current_selected_export_uses_fresh_remaining_allocation() -> None:
    """A genuinely selected current slot replaces, rather than retains, old export."""
    reconcile = _reconciler()
    state = _state(export_kwh=0.21)
    plan = {
        "available": True,
        "simulated_soc_percent": 18.0,
        "target_soc_percent": 10.0,
    }

    reconcile(
        state,
        plan,
        now=datetime(2026, 8, 28, 21, 11, tzinfo=UTC),
    )

    current = state["today_slots"][0]
    assert current["battery_export_kwh"] == 0.21
    assert current["actions"] == ["planned battery export — rolling replan"]
    assert current["current_soc_percent"] == 18.0
    assert current["ending_soc_percent"] is None


def test_future_rows_are_not_rewritten_by_current_slot_reconciliation() -> None:
    reconcile = _reconciler()
    state = _state(export_kwh=0.0)
    future_before = dict(state["today_slots"][1])

    reconcile(
        state,
        {
            "available": True,
            "simulated_soc_percent": 9.0,
            "target_soc_percent": 10.0,
        },
        now=datetime(2026, 8, 28, 21, 11, tzinfo=UTC),
    )

    assert state["today_slots"][1] == future_before


def test_current_slot_truth_is_canonical_and_write_safe() -> None:
    source = SOURCE.read_text()
    compat = COMPAT.read_text()

    assert '("agile_current_slot_truth", "install_current_slot_truth")' in compat
    assert "Real FoxESS hardware writes remain blocked" in source
    assert ".services.async_call(" not in source
    assert "safe_to_write_hardware = True" not in source
