"""Alpha8.67 regression for future Today house-discharge flow/SOC parity."""

from __future__ import annotations

import ast
import importlib.util
import json
import math
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PARITY = KEMS / "agile_flow_total_discharge_parity.py"
CONTINUITY = KEMS / "agile_live_solar_soc_continuity.py"
FLOW = KEMS / "agile_flow_presentation.py"
SLOT_FLOW = KEMS / "kems_core" / "slot_flow.py"


def _slot_flow_module():
    spec = importlib.util.spec_from_file_location("alpha867_slot_flow", SLOT_FLOW)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def _parity_and_rebase_functions():
    helpers = _base_helpers()
    slot_flow = _slot_flow_module()

    parity_tree = ast.parse(PARITY.read_text(encoding="utf-8"))
    parity_function = next(
        node
        for node in parity_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_reconcile_future_total_discharge_flow"
    )
    parity_namespace: dict[str, Any] = {
        "Any": Any,
        "_dt": helpers["_dt"],
        "_number": helpers["_number"],
        "build_slot_flow": slot_flow.build_slot_flow,
        "_EPSILON": 1e-6,
        "_LEDGER_TOLERANCE_KWH": 0.01,
        "_FLOW_TOLERANCE_KWH": 0.0005,
    }
    module = ast.Module(body=[parity_function], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, PARITY.as_posix(), "exec"), parity_namespace)

    continuity_tree = ast.parse(CONTINUITY.read_text(encoding="utf-8"))
    wanted = {"_clamp", "_battery_delta_kwh", "_rebase_display_soc"}
    continuity_functions = [
        node
        for node in continuity_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    continuity_namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "_dt": helpers["_dt"],
        "_number": helpers["_number"],
        "SimulationConfig": Any,
        "_EPSILON": 1e-6,
    }
    module = ast.Module(body=continuity_functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, CONTINUITY.as_posix(), "exec"), continuity_namespace)
    return (
        parity_namespace["_reconcile_future_total_discharge_flow"],
        continuity_namespace["_rebase_display_soc"],
    )


def _future_slot(
    *,
    valid_from: str,
    valid_to: str,
    old_soc: float,
    total: float,
    home: float,
    export: float,
    charge: float = 0.0,
) -> dict[str, Any]:
    return {
        "valid_from": valid_from,
        "valid_to": valid_to,
        "planned_total_battery_discharge_kwh": total,
        "planned_battery_to_home_kwh": home,
        "rolling_planned_battery_export_kwh": export,
        "flow_basis": "KEMS forecast + final rolling allocation",
        "flow_scope": "full slot",
        "flow_estimated_soc_percent": old_soc,
        "flow_grid_import_kwh": 0.0,
        "flow_solar_kwh": 0.0,
        "flow_solar_to_home_kwh": 0.0,
        "flow_solar_to_battery_kwh": 0.0,
        "flow_solar_export_kwh": 0.0,
        "flow_grid_to_battery_kwh": charge,
        "flow_battery_charge_kwh": charge,
        # Reproduce Alpha8.66: export was present but planned house discharge
        # disappeared from the final flow presentation.
        "flow_battery_to_home_kwh": 0.0,
        "flow_battery_export_kwh": export,
        "flow_battery_kwh": export + charge,
    }


def test_uploaded_evening_reaches_ten_percent_then_cheap_charge_handoff() -> None:
    reconcile, rebase = _parity_and_rebase_functions()
    state = {
        "current_routing_snapshot": {
            "available": True,
            "generated_at": "2026-09-01T19:27:59+00:00",
            "routing_valid_from": "2026-09-01T19:00:00+00:00",
            "routing_valid_to": "2026-09-01T19:30:00+00:00",
            "simulated_soc_percent": 38.469,
        },
        "today_slots": [
            {
                "valid_from": "2026-09-01T19:00:00+00:00",
                "valid_to": "2026-09-01T19:30:00+00:00",
                "flow_estimated_soc_percent": 38.1,
                "flow_battery_charge_kwh": 0.0,
                "flow_battery_to_home_kwh": 0.027,
                "flow_battery_export_kwh": 0.208,
            },
            _future_slot(
                valid_from="2026-09-01T19:30:00+00:00",
                valid_to="2026-09-01T20:00:00+00:00",
                old_soc=32.3,
                total=3.5,
                home=0.405,
                export=3.095,
            ),
            _future_slot(
                valid_from="2026-09-01T20:00:00+00:00",
                valid_to="2026-09-01T20:30:00+00:00",
                old_soc=26.5,
                total=3.5,
                home=0.405,
                export=3.095,
            ),
            _future_slot(
                valid_from="2026-09-01T20:30:00+00:00",
                valid_to="2026-09-01T21:00:00+00:00",
                old_soc=20.7,
                total=3.5,
                home=0.405,
                export=3.095,
            ),
            _future_slot(
                valid_from="2026-09-01T21:00:00+00:00",
                valid_to="2026-09-01T21:30:00+00:00",
                old_soc=14.9,
                total=3.5,
                home=0.405,
                export=3.095,
            ),
            _future_slot(
                valid_from="2026-09-01T21:30:00+00:00",
                valid_to="2026-09-01T22:00:00+00:00",
                old_soc=14.5,
                total=0.620,
                home=0.405,
                export=0.215,
            ),
            _future_slot(
                valid_from="2026-09-01T22:00:00+00:00",
                valid_to="2026-09-01T22:30:00+00:00",
                old_soc=14.5,
                total=0.405,
                home=0.405,
                export=0.0,
            ),
            _future_slot(
                valid_from="2026-09-01T22:30:00+00:00",
                valid_to="2026-09-01T23:00:00+00:00",
                old_soc=20.4,
                total=0.0,
                home=0.0,
                export=0.0,
                charge=3.325,
            ),
        ],
    }
    planner_fields = [
        (
            slot.get("planned_total_battery_discharge_kwh"),
            slot.get("planned_battery_to_home_kwh"),
            slot.get("rolling_planned_battery_export_kwh"),
        )
        for slot in deepcopy(state["today_slots"])
    ]

    assert reconcile(state) == 6
    config = SimpleNamespace(battery_capacity_kwh=56.42, discharge_efficiency=0.95)
    rebase(
        state,
        now=datetime(2026, 9, 1, 19, 27, 59, tzinfo=UTC),
        config=config,
    )

    active, first, second, third, fourth, fifth, sixth, cheap = state["today_slots"]
    assert active["flow_battery_to_home_kwh"] == pytest.approx(0.027)
    assert active["flow_battery_export_kwh"] == pytest.approx(0.208)
    assert first["flow_battery_to_home_kwh"] == pytest.approx(0.405)
    assert first["flow_battery_export_kwh"] == pytest.approx(3.095)
    assert first["flow_battery_kwh"] == pytest.approx(3.5)
    assert first["flow_battery_action"] == "HOME/EXPO"
    assert sixth["flow_battery_to_home_kwh"] == pytest.approx(0.405)
    assert sixth["flow_battery_export_kwh"] == 0.0
    assert sixth["flow_battery_kwh"] == pytest.approx(0.405)
    assert sixth["flow_battery_action"] == "HOME"

    assert [
        first["flow_estimated_soc_percent"],
        second["flow_estimated_soc_percent"],
        third["flow_estimated_soc_percent"],
        fourth["flow_estimated_soc_percent"],
        fifth["flow_estimated_soc_percent"],
        sixth["flow_estimated_soc_percent"],
        cheap["flow_estimated_soc_percent"],
    ] == [31.5, 25.0, 18.4, 11.9, 10.8, 10.0, 15.9]
    assert state["flow_total_discharge_parity"]["corrected_rows"] == 6
    assert state["flow_total_discharge_parity"]["reporting_only"] is True
    assert state["flow_total_discharge_parity"]["hardware_writes"] == "blocked"

    assert [
        (
            slot.get("planned_total_battery_discharge_kwh"),
            slot.get("planned_battery_to_home_kwh"),
            slot.get("rolling_planned_battery_export_kwh"),
        )
        for slot in state["today_slots"]
    ] == planner_fields


def test_alpha867_is_reporting_only_successor_with_coordinated_versions() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    source = PARITY.read_text(encoding="utf-8")
    runtime = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")

    version = str(manifest["version"])
    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert int(version.rsplit(".", 1)[-1]) >= 67
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert "TotalDischargeFlowParityAgileSmartExportManager" in runtime
    assert "IntelligentDispatchObservabilityAgileSmartExportManager" in runtime
    assert "_rebase_display_soc" in source
    assert "reporting_only" in source
    assert '"hardware_writes": "blocked"' in source
    assert "services.async_call" not in source
    assert "async_call(" not in source
