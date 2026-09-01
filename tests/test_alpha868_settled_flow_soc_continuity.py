"""Alpha8.68 regression for completed/active Today SOC continuity."""

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
        "_BACKCAST_ENERGY_TOLERANCE_KWH": 0.05,
        "_BOUNDARY_SOC_TOLERANCE_PERCENT": 0.25,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, PARITY.as_posix(), "exec"), namespace)
    return namespace["_reconcile_completed_settled_soc"]


def _completed_slot(
    *,
    label: str,
    valid_from: str,
    valid_to: str,
    stale_soc: float,
    home: float,
    export: float,
    charge: float = 0.0,
) -> dict[str, Any]:
    return {
        "label": label,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "flow_basis": "settled/replayed KEMS slot",
        "flow_estimated_soc_percent": stale_soc,
        "flow_battery_charge_kwh": charge,
        "flow_battery_to_home_kwh": home,
        "flow_battery_export_kwh": export,
        "actions": ["battery to home", "export battery at high Agile price"],
    }


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
        charge_efficiency=0.95,
        max_discharge_kw=7.0,
        max_charge_kw=7.0,
    )


def test_live_settled_boundary_replaces_impossible_replay_soc_jump() -> None:
    backcast = _backcast_function()
    state = {
        "current_routing_snapshot": {
            "available": True,
            "generated_at": "2026-09-01T20:53:21.417450+00:00",
            "routing_valid_from": "2026-09-01T20:30:00+00:00",
            "routing_valid_to": "2026-09-01T21:00:00+00:00",
            "simulated_soc_percent": 16.129,
        },
        "today_slots": [
            _completed_slot(
                label="19:30",
                valid_from="2026-09-01T18:30:00+00:00",
                valid_to="2026-09-01T19:00:00+00:00",
                stale_soc=53.2,
                home=2.063,
                export=1.218,
            ),
            _completed_slot(
                label="20:00",
                valid_from="2026-09-01T19:00:00+00:00",
                valid_to="2026-09-01T19:30:00+00:00",
                stale_soc=51.9,
                home=0.084,
                export=3.091,
            ),
            _completed_slot(
                label="20:30",
                valid_from="2026-09-01T19:30:00+00:00",
                valid_to="2026-09-01T20:00:00+00:00",
                stale_soc=45.2,
                home=0.443,
                export=3.067,
            ),
            _completed_slot(
                label="21:00",
                valid_from="2026-09-01T20:00:00+00:00",
                valid_to="2026-09-01T20:30:00+00:00",
                stale_soc=42.5,
                home=0.166,
                export=3.102,
            ),
            {
                "label": "21:30",
                "local_from": "2026-09-01T21:30:00+01:00",
                "valid_from": "2026-09-01T20:30:00+00:00",
                "valid_to": "2026-09-01T21:00:00+00:00",
                # Elapsed manager/replay energy through 21:53.
                "grid_export_kwh": 2.176,
                "solar_export_kwh": 0.0,
                "battery_to_home_kwh": 0.274,
                "solar_to_battery_kwh": 0.0,
                "grid_to_battery_kwh": 0.0,
                # Alpha8.67 canonical remaining-slot presentation.
                "flow_estimated_soc_percent": 14.7,
                "flow_battery_charge_kwh": 0.0,
                "flow_battery_to_home_kwh": 0.086,
                "flow_battery_export_kwh": 0.689,
            },
        ],
    }

    assert (
        backcast(
            state,
            now=datetime(2026, 9, 1, 20, 53, 21, tzinfo=UTC),
            config=_config(),
        )
        == 4
    )

    completed = state["today_slots"][:4]
    assert [slot["flow_estimated_soc_percent"] for slot in completed] == [
        39.3,
        33.3,
        26.8,
        20.7,
    ]
    assert state["today_slots"][4]["flow_estimated_soc_percent"] == 14.7
    assert [slot["flow_soc_pre_settlement_backcast_percent"] for slot in completed] == [
        53.2,
        51.9,
        45.2,
        42.5,
    ]
    assert all(slot["flow_settled_soc_backcast_applied"] for slot in completed)

    diagnostic = state["completed_flow_soc_continuity"]
    assert diagnostic["current_soc_percent"] == pytest.approx(16.129)
    assert diagnostic["active_start_soc_percent"] == pytest.approx(20.7, abs=0.001)
    assert diagnostic["latest_completed_pre_backcast_soc_percent"] == 42.5
    assert diagnostic["latest_completed_rebased_soc_percent"] == 20.7
    assert diagnostic["pre_backcast_boundary_jump_percent"] == pytest.approx(27.8)
    assert diagnostic["rebased_boundary_jump_percent"] == pytest.approx(6.0)
    assert diagnostic["boundary_physically_possible"] is True
    assert diagnostic["reporting_only"] is True
    assert diagnostic["hardware_writes"] == "blocked"


def test_backcast_can_reconstruct_the_persisted_local_day_seed() -> None:
    backcast = _backcast_function()
    state = {
        "current_routing_snapshot": {
            "available": True,
            "generated_at": "2026-09-01T00:10:00+00:00",
            "routing_valid_from": "2026-09-01T00:00:00+00:00",
            "routing_valid_to": "2026-09-01T00:30:00+00:00",
            "simulated_soc_percent": 50.0,
        },
        "midnight_replay_continuity": {
            "settled_rollover_seed": {
                "target_date": "2026-09-01",
                "agile_midnight_soc_percent": 54.664,
            }
        },
        "today_slots": [
            _completed_slot(
                label="00:00",
                valid_from="2026-08-31T23:00:00+00:00",
                valid_to="2026-08-31T23:30:00+00:00",
                stale_soc=70.0,
                home=0.0,
                export=1.0,
            ),
            _completed_slot(
                label="00:30",
                valid_from="2026-08-31T23:30:00+00:00",
                valid_to="2026-09-01T00:00:00+00:00",
                stale_soc=65.0,
                home=0.0,
                export=1.0,
            ),
            {
                "label": "01:00",
                "local_from": "2026-09-01T01:00:00+01:00",
                "valid_from": "2026-09-01T00:00:00+00:00",
                "valid_to": "2026-09-01T00:30:00+00:00",
                "grid_export_kwh": 0.5,
                "solar_export_kwh": 0.0,
                "battery_to_home_kwh": 0.0,
                "solar_to_battery_kwh": 0.0,
                "grid_to_battery_kwh": 0.0,
                "flow_estimated_soc_percent": 50.0,
                "flow_battery_charge_kwh": 0.0,
                "flow_battery_to_home_kwh": 0.0,
                "flow_battery_export_kwh": 0.0,
            },
        ],
    }

    assert (
        backcast(
            state,
            now=datetime(2026, 9, 1, 0, 10, tzinfo=UTC),
            config=_config(),
        )
        == 2
    )
    diagnostic = state["completed_flow_soc_continuity"]
    assert diagnostic["reached_day_start"] is True
    assert diagnostic["reconstructed_day_start_soc_percent"] == pytest.approx(54.664)
    assert diagnostic["rollover_seed_soc_percent"] == pytest.approx(54.664)
    assert diagnostic["rollover_residual_percent"] == pytest.approx(0.0, abs=0.001)


def test_alpha868_is_reporting_only_and_keeps_runtime_owner_and_coordination() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    source = PARITY.read_text(encoding="utf-8")
    runtime = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")

    assert manifest["version"] in {
        "0.8.0-alpha8.68",
        "0.8.0-alpha8.69",
        "0.8.0-alpha8.70",
    }
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert "_reconcile_completed_settled_soc" in source
    assert "flow_settled_soc_backcast_applied" in source
    assert "boundary_physically_possible" in source
    assert "TotalDischargeFlowParityAgileSmartExportManager" in runtime
    assert "IntelligentDispatchObservabilityAgileSmartExportManager" in runtime
    assert "services.async_call" not in source
    assert "async_call(" not in source
    assert '"hardware_writes": "blocked"' in source
