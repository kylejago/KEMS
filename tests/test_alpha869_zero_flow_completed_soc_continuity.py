"""Alpha8.69 regression for zero-flow completed/active SOC continuity."""

from __future__ import annotations

import ast
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PARITY = KEMS / "agile_flow_total_discharge_parity.py"
FLOW = KEMS / "agile_flow_presentation.py"


def _base_helpers() -> dict[str, Any]:
    tree = ast.parse(FLOW.read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in {"_number", "_dt"}
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "math": math,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, FLOW.as_posix(), "exec"), namespace)
    return namespace


def _backcast_function():
    helpers = _base_helpers()
    tree = ast.parse(PARITY.read_text(encoding="utf-8"))
    wanted = {
        "_active_elapsed_battery_delta_kwh",
        "_completed_display_battery_delta_kwh",
        "_maximum_full_slot_soc_swing_percent",
        "_settled_rollover_seed_soc",
        "_reconcile_completed_settled_soc",
    }
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "_dt": helpers["_dt"],
        "_number": helpers["_number"],
        "SimulationConfig": Any,
        "_EPSILON": 1e-6,
        "_FLOW_TOLERANCE_KWH": 0.0005,
        "_BACKCAST_ENERGY_TOLERANCE_KWH": 0.05,
        "_BOUNDARY_SOC_TOLERANCE_PERCENT": 0.25,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, PARITY.as_posix(), "exec"), namespace)
    return namespace["_reconcile_completed_settled_soc"]


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
        charge_efficiency=0.95,
        max_discharge_kw=7.0,
        max_charge_kw=7.0,
    )


def _completed_slot(
    *,
    label: str,
    valid_from: str,
    valid_to: str,
    stale_soc: float,
    home: float,
    export: float,
) -> dict[str, Any]:
    return {
        "label": label,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "flow_basis": "settled/replayed KEMS slot",
        "flow_estimated_soc_percent": stale_soc,
        "flow_battery_charge_kwh": 0.0,
        "flow_battery_to_home_kwh": home,
        "flow_battery_export_kwh": export,
        "actions": ["battery to home", "deadline export to protect 10% target"],
    }


def _live_zero_flow_state(*, routing_home_kw: float = 0.0) -> dict[str, Any]:
    return {
        "current_routing_snapshot": {
            "available": True,
            "generated_at": "2026-09-01T23:05:25.177578+01:00",
            "routing_valid_from": "2026-09-01T22:00:00+00:00",
            "routing_valid_to": "2026-09-01T22:30:00+00:00",
            "simulated_soc_percent": 9.757,
            "grid_to_battery_kw": 0.0,
            "battery_to_home_kw": routing_home_kw,
            "battery_export_kw": 0.0,
        },
        "today_slots": [
            _completed_slot(
                label="21:30",
                valid_from="2026-09-01T20:30:00+00:00",
                valid_to="2026-09-01T21:00:00+00:00",
                stale_soc=35.8,
                home=0.401,
                export=3.107,
            ),
            _completed_slot(
                label="22:00",
                valid_from="2026-09-01T21:00:00+00:00",
                valid_to="2026-09-01T21:30:00+00:00",
                stale_soc=31.7,
                home=0.243,
                export=1.961,
            ),
            _completed_slot(
                label="22:30",
                valid_from="2026-09-01T21:30:00+00:00",
                valid_to="2026-09-01T22:00:00+00:00",
                stale_soc=29.0,
                home=0.135,
                export=0.0,
            ),
            {
                "label": "23:00",
                "local_from": "2026-09-01T23:00:00+01:00",
                "valid_from": "2026-09-01T22:00:00+00:00",
                "valid_to": "2026-09-01T22:30:00+00:00",
                # Alpha8.68 live edge case: legacy elapsed fields unavailable.
                "grid_import_kwh": None,
                "grid_export_kwh": None,
                "solar_export_kwh": None,
                "solar_to_battery_kwh": None,
                "battery_to_home_kwh": None,
                "grid_to_battery_kwh": None,
                # Canonical current routing positively proves zero battery flow.
                "rolling_current_slot": True,
                "current_slot_plan_reconciled": True,
                "planned_total_battery_discharge_kwh": 0.0,
                "planned_battery_to_home_kwh": 0.0,
                "rolling_planned_battery_export_kwh": 0.0,
                "flow_estimated_soc_percent": 9.8,
                "flow_scope": "remaining slot",
                "flow_routing_authority": "current_routing_snapshot",
                "flow_battery_charge_kwh": 0.0,
                "flow_battery_to_home_kwh": 0.0,
                "flow_battery_export_kwh": 0.0,
            },
        ],
    }


def test_live_zero_flow_active_slot_allows_completed_soc_backcast() -> None:
    backcast = _backcast_function()
    state = _live_zero_flow_state()

    assert (
        backcast(
            state,
            now=datetime(2026, 9, 1, 22, 5, 25, tzinfo=UTC),
            config=_config(),
        )
        == 3
    )

    completed = state["today_slots"][:3]
    assert [slot["flow_estimated_soc_percent"] for slot in completed] == [
        14.1,
        10.0,
        9.8,
    ]
    assert state["today_slots"][3]["flow_estimated_soc_percent"] == 9.8
    assert [slot["flow_soc_pre_settlement_backcast_percent"] for slot in completed] == [
        35.8,
        31.7,
        29.0,
    ]

    diagnostic = state["completed_flow_soc_continuity"]
    assert diagnostic["applied"] is True
    assert diagnostic["canonical_zero_flow_fallback_used"] is True
    assert diagnostic["active_elapsed_battery_delta_kwh"] == pytest.approx(0.0)
    assert (
        diagnostic["active_elapsed_battery_delta_source"]
        == "canonical current routing proven zero battery flow"
    )
    assert diagnostic["latest_completed_pre_backcast_soc_percent"] == 29.0
    assert diagnostic["latest_completed_rebased_soc_percent"] == 9.8
    assert diagnostic["pre_backcast_boundary_jump_percent"] == pytest.approx(19.2)
    assert diagnostic["rebased_boundary_jump_percent"] == pytest.approx(0.0)
    assert diagnostic["boundary_physically_possible"] is True
    assert diagnostic["reporting_only"] is True
    assert diagnostic["hardware_writes"] == "blocked"


def test_zero_flow_fallback_fails_closed_when_live_routing_is_nonzero() -> None:
    backcast = _backcast_function()
    state = _live_zero_flow_state(routing_home_kw=0.1)

    assert (
        backcast(
            state,
            now=datetime(2026, 9, 1, 22, 5, 25, tzinfo=UTC),
            config=_config(),
        )
        == 0
    )

    diagnostic = state["completed_flow_soc_continuity"]
    assert diagnostic["applied"] is False
    assert diagnostic["reason"] == "active elapsed battery energy unavailable"
    assert diagnostic["canonical_zero_flow_fallback_used"] is False
    assert diagnostic["canonical_zero_flow_proven"] is False
    assert state["today_slots"][2]["flow_estimated_soc_percent"] == 29.0


def test_alpha869_is_reporting_only_and_keeps_coordination() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    source = PARITY.read_text(encoding="utf-8")
    runtime = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")

    assert manifest["version"] == "0.8.0-alpha8.69"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert "canonical current routing proven zero battery flow" in source
    assert "canonical_zero_flow_fallback_used" in source
    assert "TotalDischargeFlowParityAgileSmartExportManager" in runtime
    assert "services.async_call" not in source
    assert "async_call(" not in source
    assert '"hardware_writes": "blocked"' in source
