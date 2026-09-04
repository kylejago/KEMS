"""Alpha8.72 regressions for restart-only SOC boundary anchoring."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
ANCHOR = KEMS / "agile_restart_soc_anchor.py"
RUNTIME = KEMS / "agile_smart_export_runtime.py"


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
        charge_efficiency=0.95,
        max_discharge_kw=7.0,
        max_charge_kw=7.0,
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _candidate_function():
    tree = ast.parse(ANCHOR.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_restart_boundary_anchor_candidate"
    )
    namespace: dict[str, Any] = {
        "Any": Any,
        "SimulationConfig": Any,
        "_number": _number,
        "_EPSILON": 1e-6,
        "_ROLLOVER_ANCHOR_TOLERANCE_PERCENT": 0.25,
    }
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, ANCHOR.as_posix(), "exec"), namespace)
    return namespace["_restart_boundary_anchor_candidate"]


def _live_restart_state() -> dict[str, Any]:
    return {
        "current_routing_snapshot": {
            "available": True,
            "generated_at": "2026-09-02T17:42:35.242039+01:00",
            "routing_valid_from": "2026-09-02T16:30:00+00:00",
            "routing_valid_to": "2026-09-02T17:00:00+00:00",
            "simulated_soc_percent": 63.195,
        },
        "completed_flow_soc_continuity": {
            "active": True,
            "applied": True,
            "current_soc_percent": 63.195,
            "active_start_soc_percent": 65.512,
            "active_elapsed_battery_delta_kwh": -1.307114,
            "active_elapsed_battery_delta_source": (
                "persisted Agile charge/total-discharge decisions"
            ),
            "reconstructed_day_start_soc_percent": 18.741,
            "rollover_seed_soc_percent": 16.388,
            "rollover_residual_percent": 2.353,
            "canonical_decision_elapsed_fallback_used": True,
            "canonical_decision_elapsed_available": True,
            "canonical_decision_elapsed_seconds": 755.242,
            "canonical_decision_elapsed_segments": 11,
            "canonical_decision_count": 12,
            "canonical_decision_stored_charge_kwh": 0.0,
            "canonical_decision_discharge_ac_kwh": 1.241758,
            "reporting_only": True,
            "hardware_writes": "blocked",
        },
    }


def test_live_restart_evidence_selects_boundary_anchor_and_closes_rollover() -> None:
    candidate = _candidate_function()(_live_restart_state(), _config())

    assert candidate is not None
    assert candidate["routing_soc_percent"] == pytest.approx(63.195)
    assert candidate["display_current_soc_percent"] == pytest.approx(
        60.878244, abs=1e-6
    )
    assert candidate["stored_delta_percent"] == pytest.approx(-2.316756, abs=1e-6)
    assert candidate["rollover_residual_before_percent"] == pytest.approx(2.353)
    assert candidate["rollover_residual_candidate_percent"] == pytest.approx(
        0.036244, abs=1e-6
    )


def test_already_continuous_elapsed_current_soc_is_not_reanchored() -> None:
    state = _live_restart_state()
    diagnostic = state["completed_flow_soc_continuity"]
    diagnostic["rollover_residual_percent"] = 0.004

    assert _candidate_function()(state, _config()) is None


def test_boundary_reconciliation_uses_temporary_display_soc_and_restores_routing() -> (
    None
):
    tree = ast.parse(ANCHOR.read_text(encoding="utf-8"))
    names = {
        "_restart_boundary_anchor_candidate",
        "_reconcile_restart_boundary_anchor",
    }
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    captures: dict[str, Any] = {}

    def dt(value: Any) -> Any:
        return value

    def rebase(state: dict[str, Any], *, now: Any, config: Any) -> None:
        captures["rebase_soc"] = state["current_routing_snapshot"][
            "simulated_soc_percent"
        ]
        captures["rebase_now"] = now
        captures["rebase_config"] = config

    def reconcile(state: dict[str, Any], *, now: Any, config: Any) -> int:
        captures["reconcile_soc"] = state["current_routing_snapshot"][
            "simulated_soc_percent"
        ]
        captures["synthetic_grid_export"] = state["today_slots"][0]["grid_export_kwh"]
        # Mirror the real helper replacing the diagnostic dictionary.
        state["completed_flow_soc_continuity"] = {
            "active": True,
            "applied": True,
            "current_soc_percent": 60.878,
            "active_start_soc_percent": 63.195,
            "reconstructed_day_start_soc_percent": 16.424,
            "rollover_seed_soc_percent": 16.388,
            "rollover_residual_percent": 0.036,
            "reporting_only": True,
            "hardware_writes": "blocked",
        }
        return 35

    namespace: dict[str, Any] = {
        "Any": Any,
        "SimulationConfig": Any,
        "_number": _number,
        "_dt": dt,
        "_EPSILON": 1e-6,
        "_ROLLOVER_ANCHOR_TOLERANCE_PERCENT": 0.25,
        "_rebase_display_soc": rebase,
        "_reconcile_completed_settled_soc": reconcile,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, ANCHOR.as_posix(), "exec"), namespace)

    state = _live_restart_state()
    state["today_slots"] = [
        {
            "valid_from": "2026-09-02T16:30:00+00:00",
            "valid_to": "2026-09-02T17:00:00+00:00",
            "grid_export_kwh": None,
            "solar_export_kwh": None,
            "battery_to_home_kwh": None,
            "solar_to_battery_kwh": None,
            "grid_to_battery_kwh": None,
        }
    ]
    original_routing_soc = state["current_routing_snapshot"]["simulated_soc_percent"]

    corrected = namespace["_reconcile_restart_boundary_anchor"](
        state,
        now="2026-09-02T17:42:35.242039+01:00",
        config=_config(),
    )

    assert corrected == 35
    assert captures["rebase_soc"] == pytest.approx(60.878244, abs=1e-6)
    assert captures["reconcile_soc"] == pytest.approx(60.878244, abs=1e-6)
    assert captures["synthetic_grid_export"] == pytest.approx(1.241758)
    assert state["current_routing_snapshot"]["simulated_soc_percent"] == pytest.approx(
        original_routing_soc
    )
    assert state["today_slots"][0]["grid_export_kwh"] is None

    diagnostic = state["completed_flow_soc_continuity"]
    assert diagnostic["active_start_soc_percent"] == pytest.approx(63.195)
    assert diagnostic["rollover_residual_percent"] == pytest.approx(0.036)
    assert diagnostic["canonical_decision_elapsed_fallback_used"] is True
    assert (
        diagnostic["canonical_decision_soc_anchor_mode"]
        == "settled active-slot boundary proven by rollover continuity"
    )
    assert diagnostic["canonical_decision_routing_soc_unchanged"] is True
    assert diagnostic["canonical_decision_routing_soc_percent"] == pytest.approx(63.195)
    assert diagnostic[
        "canonical_decision_display_current_soc_percent"
    ] == pytest.approx(60.878)
    assert diagnostic["hardware_writes"] == "blocked"


def test_final_owner_publishes_provider_identity_after_replacement_helpers() -> None:
    source = ANCHOR.read_text(encoding="utf-8")
    provider_index = source.index('diagnostic["canonical_decision_provider_bound"]')
    fallback_index = source.index("_reconcile_completed_from_persisted_decisions(")
    anchor_index = source.index("_reconcile_restart_boundary_anchor(")

    assert fallback_index < provider_index
    assert anchor_index < provider_index
    assert 'diagnostic["canonical_decision_history_source"] = history_source' in source
    assert "services.async_call" not in source
    assert "async_call(" not in source


def test_alpha872_contract_survives_successor_releases() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    runtime = RUNTIME.read_text(encoding="utf-8")
    anchor = ANCHOR.read_text(encoding="utf-8")

    version = manifest["version"]
    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    release_number = int(version.rsplit(".", 1)[1])
    assert release_number >= 72
    assert (
        "EfficientAgileSmartExportManager = RestartSocAnchorAgileSmartExportManager"
        in runtime
    )
    assert "agile_restart_soc_anchor" in runtime
    if release_number == 72:
        assert "routing/optimiser state unchanged" in bundle["maintenance"]["reason"]
        assert "reporting-only" in bundle["maintenance"]["reason"]
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    assert "hardware_writes" in anchor
    assert "services.async_call" not in anchor
