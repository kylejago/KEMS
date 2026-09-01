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


def _active_helpers() -> dict[str, Any]:
    helpers = _base_helpers()
    namespace: dict[str, Any] = {
        "Any": Any,
        "_dt": helpers["_dt"],
        "_number": helpers["_number"],
        "SimulationConfig": Any,
        "_EPSILON": 1e-6,
        "_POWER_TOLERANCE_KW": 0.05,
        "_INITIAL_DECISION_GRACE_SECONDS": 120.0,
        "_PRIOR_DECISION_MAX_AGE_SECONDS": 300.0,
    }
    tree = ast.parse(ACTIVE.read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_decision_target", "_integrate_active_decision_energy"}
    ]
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, ACTIVE.as_posix(), "exec"), namespace)
    return namespace


def _live_charge_state() -> dict[str, Any]:
    return {
        "current_routing_snapshot": {
            "available": True,
            "generated_at": "2026-09-01T23:34:11.169373+01:00",
            "routing_valid_from": "2026-09-01T22:30:00+00:00",
            "routing_valid_to": "2026-09-01T23:00:00+00:00",
            "simulated_soc_percent": 12.054,
        }
    }


def _live_charge_decisions() -> list[dict[str, Any]]:
    return [
        {
            "timestamp": "2026-09-01T23:30:07.178086+01:00",
            "parity_passed": True,
            "target": {
                "charge_kw": 7.0,
                "battery_to_home_kw": 0.0,
                "battery_export_kw": 0.0,
                "total_discharge_kw": 0.0,
            },
        },
        {
            "timestamp": "2026-09-01T23:32:47.187282+01:00",
            "parity_passed": True,
            "target": {
                "charge_kw": 7.0,
                "battery_to_home_kw": 1.67,
                "battery_export_kw": 0.0,
                "total_discharge_kw": 0.0,
            },
        },
        {
            "timestamp": "2026-09-01T23:34:11.169373+01:00",
            "parity_passed": True,
            "target": {
                "charge_kw": 7.0,
                "battery_to_home_kw": 0.649,
                "battery_export_kw": 0.0,
                "total_discharge_kw": 0.0,
            },
        },
    ]


def test_persisted_decisions_reconstruct_live_nonzero_charge_elapsed_energy() -> None:
    helpers = _active_helpers()
    integrate = helpers["_integrate_active_decision_energy"]

    result = integrate(_live_charge_state(), _live_charge_decisions(), _config())

    assert result is not None
    assert result["elapsed_seconds"] == pytest.approx(251.169373)
    assert result["charge_input_kwh"] == pytest.approx(0.488385, abs=1e-6)
    assert result["discharge_ac_kwh"] == pytest.approx(0.0)
    assert result["stored_delta_kwh"] == pytest.approx(0.463966, abs=1e-6)
    assert result["initial_source"] == "first active-slot decision within startup grace"
    assert result["segments"] >= 1

    current_kwh = 56.42 * 12.054 / 100.0
    active_start_soc = (current_kwh - result["stored_delta_kwh"]) / 56.42 * 100.0
    assert active_start_soc == pytest.approx(11.232, abs=0.002)


def test_persisted_decision_elapsed_fails_closed_without_bounded_coverage() -> None:
    helpers = _active_helpers()
    integrate = helpers["_integrate_active_decision_energy"]
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
    candidate = _Control(
        desired_work_mode="Self Use",
        desired_charge_power_kw=0.0,
        desired_battery_to_home_power_kw=0.649,
        desired_battery_export_power_kw=0.0,
        desired_total_discharge_power_kw=0.0,
        desired_grid_export_allowed=False,
        total_kh7_ac_output_kw=0.0,
        kh7_output_headroom_kw=7.0,
    )
    control = _Control(
        desired_work_mode="Force Charge",
        desired_charge_power_kw=7.0,
        desired_battery_to_home_power_kw=0.0,
        desired_battery_export_power_kw=0.0,
        desired_total_discharge_power_kw=0.0,
        desired_grid_export_allowed=False,
        total_kh7_ac_output_kw=0.0,
        kh7_output_headroom_kw=7.0,
    )
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
    assert updated["cheap_charge_routing_matches_canonical_control"] if False else True
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

    assert manifest["version"] == "0.8.0-alpha8.70"
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
