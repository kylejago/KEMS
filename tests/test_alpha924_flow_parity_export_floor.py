"""Alpha9.24 regression for planning-target export caps after flow parity."""

from __future__ import annotations

import ast
import importlib.util
import json
import math
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PARITY = KEMS / "agile_flow_total_discharge_parity.py"
POLICY_PARITY = KEMS / "agile_flow_policy_parity.py"
RESTART_OWNER = KEMS / "agile_restart_soc_anchor.py"
SLOT_FLOW = KEMS / "kems_core" / "slot_flow.py"


def _slot_flow_module():
    spec = importlib.util.spec_from_file_location("alpha924_slot_flow", SLOT_FLOW)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _dt(value: Any) -> datetime | None:
    """Match the runtime's aware-UTC timestamp normalisation for the AST test."""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _number(value: Any) -> float | None:
    """Match the runtime's finite-number coercion for the isolated parity test."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _reconcilers():
    """Load the real parity functions without importing Home Assistant."""
    slot_flow = _slot_flow_module()
    tree = ast.parse(PARITY.read_text(encoding="utf-8"))
    wanted = {"_reconcile_future_total_discharge_flow"}
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "math": math,
        "_dt": _dt,
        "_number": _number,
        "build_slot_flow": slot_flow.build_slot_flow,
        "_EPSILON": 1e-6,
        "_LEDGER_TOLERANCE_KWH": 0.01,
        "_FLOW_TOLERANCE_KWH": 0.0005,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, PARITY.as_posix(), "exec"), namespace)

    policy_tree = ast.parse(POLICY_PARITY.read_text(encoding="utf-8"))
    policy_functions = [
        node for node in policy_tree.body if isinstance(node, ast.FunctionDef)
    ]
    policy_namespace: dict[str, Any] = {
        "Any": Any,
        "math": math,
        "_dt": _dt,
        "_reconcile_future_total_discharge_flow": namespace[
            "_reconcile_future_total_discharge_flow"
        ],
        "_EPSILON": 1e-6,
        "_FLOW_TOLERANCE_KWH": 0.0005,
    }
    policy_module = ast.Module(body=policy_functions, type_ignores=[])
    ast.fix_missing_locations(policy_module)
    exec(compile(policy_module, POLICY_PARITY.as_posix(), "exec"), policy_namespace)
    return (
        namespace["_reconcile_future_total_discharge_flow"],
        policy_namespace["_reconcile_future_policy_safe_total_discharge_flow"],
    )


def _slot(
    *,
    valid_from: str,
    valid_to: str,
    planned_total: float,
    planned_home: float,
    planned_export: float,
    flow_home: float,
    flow_export: float,
    policy: bool,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "valid_from": valid_from,
        "valid_to": valid_to,
        "planned_total_battery_discharge_kwh": planned_total,
        "planned_battery_to_home_kwh": planned_home,
        "rolling_planned_battery_export_kwh": planned_export,
        "flow_basis": "KEMS forecast + final rolling allocation",
        "flow_scope": "full slot",
        "flow_estimated_soc_percent": 15.0,
        "flow_grid_import_kwh": 0.0,
        "flow_solar_kwh": 0.0,
        "flow_solar_to_home_kwh": 0.0,
        "flow_solar_to_battery_kwh": 0.0,
        "flow_solar_export_kwh": 0.0,
        "flow_grid_to_battery_kwh": 0.0,
        "flow_battery_charge_kwh": 0.0,
        "flow_battery_to_home_kwh": flow_home,
        "flow_battery_export_kwh": flow_export,
        "flow_battery_kwh": flow_home + flow_export,
    }
    if policy:
        row.update(
            {
                "planning_target_soc_percent": 15.0,
                "house_import_floor_soc_percent": 10.0,
                "hard_safety_recovery_soc_percent": 12.0,
                "planning_target_limits_export_only": True,
                "hard_safety_floor_latched": False,
            }
        )
    return row


def _live_failure_state(*, policy: bool = True) -> dict[str, Any]:
    return {
        "current_routing_snapshot": {
            "available": True,
            "generated_at": "2026-09-10T21:58:00+00:00",
            "routing_valid_from": "2026-09-10T21:30:00+00:00",
            "routing_valid_to": "2026-09-10T22:00:00+00:00",
        },
        "today_slots": [
            _slot(
                valid_from="2026-09-10T22:00:00+00:00",
                valid_to="2026-09-10T22:30:00+00:00",
                planned_total=0.706,
                planned_home=0.706,
                planned_export=0.0,
                flow_home=0.706,
                flow_export=0.0,
                policy=policy,
            ),
            _slot(
                valid_from="2026-09-10T22:30:00+00:00",
                valid_to="2026-09-10T23:00:00+00:00",
                planned_total=1.102,
                planned_home=0.706,
                planned_export=0.396,
                flow_home=0.706,
                flow_export=0.204,
                policy=policy,
            ),
        ],
    }


def test_live_alpha923_overwrite_is_reproduced_then_blocked() -> None:
    """Legacy parity raises 0.204 to 0.396; Alpha9.24 must preserve the cap."""
    legacy_reconcile, policy_reconcile = _reconcilers()

    legacy = _live_failure_state()
    assert legacy_reconcile(legacy) == 1
    assert legacy["today_slots"][1]["flow_battery_export_kwh"] == pytest.approx(0.396)
    assert legacy["today_slots"][1]["flow_battery_kwh"] == pytest.approx(1.102)

    protected = _live_failure_state()
    planner_before = [
        (
            row["planned_total_battery_discharge_kwh"],
            row["planned_battery_to_home_kwh"],
            row["rolling_planned_battery_export_kwh"],
        )
        for row in deepcopy(protected["today_slots"])
    ]

    policy_reconcile(protected)

    first, second = protected["today_slots"]
    assert first["flow_battery_to_home_kwh"] == pytest.approx(0.706)
    assert first["flow_battery_export_kwh"] == pytest.approx(0.0)
    assert second["flow_battery_to_home_kwh"] == pytest.approx(0.706)
    assert second["flow_battery_export_kwh"] == pytest.approx(0.204)
    assert second["flow_battery_kwh"] == pytest.approx(0.910)
    assert second["flow_grid_import_kwh"] == pytest.approx(0.0)
    assert second["planning_target_soc_percent"] == pytest.approx(15.0)
    assert second["house_import_floor_soc_percent"] == pytest.approx(10.0)
    assert second["hard_safety_recovery_soc_percent"] == pytest.approx(12.0)
    assert second["planning_target_limits_export_only"] is True
    assert second["flow_policy_export_cap_applied"] is True
    assert second["flow_policy_export_cap_kwh"] == pytest.approx(0.204)
    assert second["flow_policy_rolling_export_kwh"] == pytest.approx(0.396)
    assert second["flow_policy_suppressed_export_kwh"] == pytest.approx(0.192)
    assert second["flow_policy_planner_fields_unchanged"] is True
    assert protected["flow_total_discharge_parity"]["policy_export_cap_rows"] == 1
    assert (
        protected["flow_total_discharge_parity"]["policy_export_cap_preserved"] is True
    )
    assert protected["flow_total_discharge_parity"]["planner_fields_unchanged"] is True
    assert [
        (
            row["planned_total_battery_discharge_kwh"],
            row["planned_battery_to_home_kwh"],
            row["rolling_planned_battery_export_kwh"],
        )
        for row in protected["today_slots"]
    ] == planner_before


def test_legacy_rows_without_export_only_policy_keep_alpha867_parity() -> None:
    """The new guard must not change historical rows without Alpha9 policy proof."""
    _, policy_reconcile = _reconcilers()
    state = _live_failure_state(policy=False)

    assert policy_reconcile(state) == 1
    assert state["today_slots"][1]["flow_battery_export_kwh"] == pytest.approx(0.396)
    assert state["today_slots"][1]["flow_battery_kwh"] == pytest.approx(1.102)


def test_alpha924_runtime_uses_policy_safe_final_publication_owner() -> None:
    """The final restart-safe owner must invoke the new guard, not legacy parity."""
    source = RESTART_OWNER.read_text(encoding="utf-8")
    policy_source = POLICY_PARITY.read_text(encoding="utf-8")
    assert "from .agile_flow_policy_parity import" in source
    assert "_reconcile_future_policy_safe_total_discharge_flow(state)" in source
    assert "_reconcile_future_total_discharge_flow(state)" not in source
    assert "_dt," in policy_source


def test_alpha924_release_scope_remains_reporting_only() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    source = POLICY_PARITY.read_text(encoding="utf-8")

    assert manifest["version"] == "0.9.0-alpha9.29"
    reason = bundle["maintenance"]["reason"].lower()
    assert "alpha9.24" in reason
    assert "flow parity" in reason
    assert "15%" in reason
    assert "10%" in reason
    assert "12%" in reason
    assert "reporting-only" in source
    assert "services.async_call" not in source
    assert "async_call(" not in source
    assert "commands_permitted = true" not in source.lower()
    assert "safe_to_write_hardware = true" not in source.lower()
