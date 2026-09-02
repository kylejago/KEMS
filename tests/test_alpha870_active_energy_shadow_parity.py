"""Alpha8.70 regressions for restart-safe SOC and cheap-charge shadow truth."""

from __future__ import annotations

import ast
import json
import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
ACTIVE = KEMS / "agile_active_elapsed_soc_continuity.py"
PARITY = KEMS / "agile_flow_total_discharge_parity.py"
FLOW = KEMS / "agile_flow_presentation.py"
SHADOW = KEMS / "agile_shadow_charge_truth.py"


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
        charge_efficiency=0.95,
        max_discharge_kw=7.0,
        max_charge_kw=7.0,
    )


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


def _load_backcast_namespace() -> dict[str, Any]:
    helpers = _base_helpers()
    namespace: dict[str, Any] = {
        "Any": Any,
        "_dt": helpers["_dt"],
        "_number": helpers["_number"],
        "SimulationConfig": Any,
        "_EPSILON": 1e-6,
        "_FLOW_TOLERANCE_KWH": 0.0005,
        "_BACKCAST_ENERGY_TOLERANCE_KWH": 0.05,
        "_BOUNDARY_SOC_TOLERANCE_PERCENT": 0.25,
        "_POWER_TOLERANCE_KW": 0.05,
        "_INITIAL_DECISION_GRACE_SECONDS": 120.0,
        "_PRIOR_DECISION_MAX_AGE_SECONDS": 300.0,
    }
    parity_tree = ast.parse(PARITY.read_text(encoding="utf-8"))
    parity_names = {
        "_active_elapsed_battery_delta_kwh",
        "_completed_display_battery_delta_kwh",
        "_maximum_full_slot_soc_swing_percent",
        "_settled_rollover_seed_soc",
        "_reconcile_completed_settled_soc",
    }
    parity_functions = [
        node
        for node in parity_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in parity_names
    ]
    parity_module = ast.Module(body=parity_functions, type_ignores=[])
    ast.fix_missing_locations(parity_module)
    exec(compile(parity_module, PARITY.as_posix(), "exec"), namespace)

    active_tree = ast.parse(ACTIVE.read_text(encoding="utf-8"))
    active_names = {
        "_decision_target",
        "_integrate_active_decision_energy",
        "_reconcile_completed_from_persisted_decisions",
    }
    active_functions = [
        node
        for node in active_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in active_names
    ]
    active_module = ast.Module(body=active_functions, type_ignores=[])
    ast.fix_missing_locations(active_module)
    exec(compile(active_module, ACTIVE.as_posix(), "exec"), namespace)
    return namespace


def _completed_slot(
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
        "flow_estimated_soc_percent": stale_soc,
        "flow_battery_charge_kwh": 0.0,
        "flow_battery_to_home_kwh": home,
        "flow_battery_export_kwh": export,
        "actions": ["battery to home", "deadline export to protect 10% target"],
    }


def _live_charge_state() -> dict[str, Any]:
    return {
        "current_routing_snapshot": {
            "available": True,
            "generated_at": "2026-09-01T23:34:11.169373+01:00",
            "routing_valid_from": "2026-09-01T22:30:00+00:00",
            "routing_valid_to": "2026-09-01T23:00:00+00:00",
            "simulated_soc_percent": 12.054,
        },
        "today_slots": [
            _completed_slot(
                "21:30",
                "2026-09-01T20:30:00+00:00",
                "2026-09-01T21:00:00+00:00",
                35.8,
                0.401,
                3.107,
            ),
            _completed_slot(
                "22:00",
                "2026-09-01T21:00:00+00:00",
                "2026-09-01T21:30:00+00:00",
                31.7,
                0.243,
                1.961,
            ),
            _completed_slot(
                "22:30",
                "2026-09-01T21:30:00+00:00",
                "2026-09-01T22:00:00+00:00",
                29.0,
                0.135,
                0.0,
            ),
            _completed_slot(
                "23:00",
                "2026-09-01T22:00:00+00:00",
                "2026-09-01T22:30:00+00:00",
                27.7,
                0.074,
                0.0,
            ),
            {
                "label": "23:30",
                "valid_from": "2026-09-01T22:30:00+00:00",
                "valid_to": "2026-09-01T23:00:00+00:00",
                "grid_import_kwh": None,
                "grid_export_kwh": None,
                "solar_export_kwh": None,
                "solar_to_battery_kwh": None,
                "battery_to_home_kwh": None,
                "grid_to_battery_kwh": None,
                "flow_estimated_soc_percent": 17.4,
                "flow_battery_charge_kwh": 3.012,
                "flow_battery_to_home_kwh": 0.0,
                "flow_battery_export_kwh": 0.0,
                "flow_scope": "remaining slot",
                "flow_routing_authority": "current_routing_snapshot",
            },
        ],
        "completed_flow_soc_continuity": {
            "active": True,
            "applied": False,
            "reason": "active elapsed battery energy unavailable",
            "reporting_only": True,
            "hardware_writes": "blocked",
        },
    }


def _live_charge_decisions() -> list[dict[str, Any]]:
    return [
        {
            "timestamp": "2026-09-01T23:30:07.178086+01:00",
            "target": {"charge_kw": 7.0, "total_discharge_kw": 0.0},
        },
        {
            "timestamp": "2026-09-01T23:32:47.187282+01:00",
            # Alpha8.69's subsidiary shadow had a bad home split, but its
            # canonical charge and authoritative total-discharge targets were
            # still correct; Alpha8.70 intentionally integrates those two fields.
            "target": {
                "charge_kw": 7.0,
                "battery_to_home_kw": 1.67,
                "total_discharge_kw": 0.0,
            },
        },
        {
            "timestamp": "2026-09-01T23:34:11.169373+01:00",
            "target": {
                "charge_kw": 7.0,
                "battery_to_home_kw": 0.649,
                "total_discharge_kw": 0.0,
            },
        },
    ]


def test_persisted_decisions_reconstruct_live_nonzero_charge_elapsed_energy() -> None:
    namespace = _load_backcast_namespace()
    integrate = namespace["_integrate_active_decision_energy"]
    result = integrate(_live_charge_state(), _live_charge_decisions(), _config())

    assert result is not None
    assert result["elapsed_seconds"] == pytest.approx(251.169373)
    assert result["charge_input_kwh"] == pytest.approx(0.488385, abs=1e-6)
    assert result["stored_charge_kwh"] == pytest.approx(0.463966, abs=1e-6)
    assert result["discharge_ac_kwh"] == pytest.approx(0.0)
    assert result["stored_delta_kwh"] == pytest.approx(0.463966, abs=1e-6)
    assert result["initial_source"] == "first active-slot decision within startup grace"


def test_live_charge_restart_rebases_completed_rows_onto_settled_soc_timeline() -> None:
    namespace = _load_backcast_namespace()
    reconcile = namespace["_reconcile_completed_from_persisted_decisions"]
    state = _live_charge_state()

    assert (
        reconcile(
            state,
            decisions=_live_charge_decisions(),
            now=datetime(2026, 9, 1, 22, 34, 11, 169373, tzinfo=UTC),
            config=_config(),
        )
        == 4
    )

    completed = state["today_slots"][:4]
    assert [row["flow_estimated_soc_percent"] for row in completed] == [
        15.7,
        11.6,
        11.4,
        11.2,
    ]
    assert [row["flow_soc_pre_settlement_backcast_percent"] for row in completed] == [
        35.8,
        31.7,
        29.0,
        27.7,
    ]
    assert state["today_slots"][4]["flow_estimated_soc_percent"] == 17.4

    diagnostic = state["completed_flow_soc_continuity"]
    assert diagnostic["applied"] is True
    assert diagnostic["active_start_soc_percent"] == pytest.approx(11.232, abs=0.002)
    assert diagnostic["latest_completed_rebased_soc_percent"] == 11.2
    assert diagnostic["canonical_decision_elapsed_fallback_used"] is True
    assert diagnostic["canonical_decision_elapsed_available"] is True
    assert diagnostic["active_elapsed_battery_delta_kwh"] == pytest.approx(
        0.463966, abs=1e-6
    )
    assert (
        diagnostic["active_elapsed_battery_delta_source"]
        == "persisted Agile charge/total-discharge decisions"
    )
    assert diagnostic["boundary_physically_possible"] is True
    assert diagnostic["reporting_only"] is True
    assert diagnostic["hardware_writes"] == "blocked"


def test_persisted_decision_elapsed_fails_closed_without_bounded_coverage() -> None:
    namespace = _load_backcast_namespace()
    integrate = namespace["_integrate_active_decision_energy"]
    decisions = [
        {
            "timestamp": "2026-09-01T23:35:00+01:00",
            "target": {"charge_kw": 7.0, "total_discharge_kw": 0.0},
        }
    ]
    assert integrate(_live_charge_state(), decisions, _config()) is None


@dataclass(frozen=True)
class _Control:
    desired_work_mode: str
    desired_charge_power_kw: float
    desired_battery_to_home_power_kw: float
    desired_battery_export_power_kw: float
    desired_total_discharge_power_kw: float
    desired_grid_export_allowed: bool
    total_kh7_ac_output_kw: float
    kh7_output_headroom_kw: float
    operating_reason: str = "agile_rolling_cheap_charge"


def _shadow_reconcile():
    tree = ast.parse(SHADOW.read_text(encoding="utf-8"))
    body = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_number", "reconcile_cheap_charge_target"}
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "ControlState": Any,
        "replace": replace,
    }
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, SHADOW.as_posix(), "exec"), namespace)
    return namespace["reconcile_cheap_charge_target"]


def test_cheap_charge_shadow_uses_canonical_zero_discharge_routing() -> None:
    reconcile = _shadow_reconcile()
    candidate = _Control("Self Use", 0.0, 0.649, 0.0, 0.0, False, 0.0, 7.0)
    control = _Control("Force Charge", 7.0, 0.0, 0.0, 0.0, False, 0.0, 7.0)
    context = {
        "dispatch_mode": "cheap_charge",
        "optimizer_target": {
            "battery_to_home_kw": 0.649,
            "battery_export_kw": 0.0,
            "total_discharge_kw": 0.0,
        },
        "parity": {
            "house_target_matches_optimizer": True,
            "export_target_matches_optimizer": True,
            "discharge_target_matches_optimizer": True,
        },
    }

    corrected, updated = reconcile(candidate, context, control)

    assert corrected is not None
    assert corrected.desired_work_mode == "Force Charge"
    assert corrected.desired_charge_power_kw == 7.0
    assert corrected.desired_battery_to_home_power_kw == 0.0
    assert corrected.desired_battery_export_power_kw == 0.0
    assert corrected.desired_total_discharge_power_kw == 0.0
    assert corrected.desired_grid_export_allowed is False
    assert (
        corrected.desired_battery_to_home_power_kw
        + corrected.desired_battery_export_power_kw
        <= corrected.desired_total_discharge_power_kw
    )
    assert updated["optimizer_target"] == {
        "battery_to_home_kw": 0.0,
        "battery_export_kw": 0.0,
        "total_discharge_kw": 0.0,
        "charge_kw": 7.0,
    }
    assert updated["parity_passed"] is True
    assert updated["parity"]["cheap_charge_routing_matches_canonical_control"] is True
    assert updated["cheap_charge_routing_source"] == "canonical ControlState"
    assert updated["hardware_writes"] == "blocked"


def test_alpha870_is_reporting_parity_only_and_keeps_coordination() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    active_source = ACTIVE.read_text(encoding="utf-8")
    shadow_source = SHADOW.read_text(encoding="utf-8")
    runtime = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")

    version = manifest["version"]
    assert version.startswith("0.8.0-alpha8.")
    assert int(version.rsplit(".", 1)[1]) >= 70
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert "persisted Agile charge/total-discharge decisions" in active_source
    assert "canonical_decision_elapsed_fallback_used" in active_source
    assert "cheap_charge_routing_source" in shadow_source
    assert "ActiveElapsedSocContinuityAgileSmartExportManager" in runtime
    assert "services.async_call" not in active_source
    assert "async_call(" not in active_source
    assert '"hardware_writes": "blocked"' in active_source
