"""Alpha8.71 regression for recorder-owned persisted Agile decision wiring."""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
ACTIVE = KEMS / "agile_active_elapsed_soc_continuity.py"
COORDINATOR = KEMS / "coordinator.py"
ALPHA723 = KEMS / "agile_alpha723_shadow.py"


class _TotalDischargeBase:
    pass


class _ObservabilityBase:
    published = False

    @staticmethod
    def _publish(_manager: Any, _state: dict[str, Any]) -> None:
        _ObservabilityBase.published = True


class _SimulationConfig:
    pass


def _manager_class(capture: dict[str, Any]):
    tree = ast.parse(ACTIVE.read_text(encoding="utf-8"))
    cls = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "ActiveElapsedSocContinuityAgileSmartExportManager"
    )

    def reconcile_from_decisions(
        state: dict[str, Any],
        *,
        decisions: list[dict[str, Any]],
        now: Any,
        config: Any,
    ) -> int:
        capture["decisions"] = decisions
        capture["now"] = now
        capture["config"] = config
        state["completed_flow_soc_continuity"]["applied"] = True
        return 3

    namespace: dict[str, Any] = {
        "Any": Any,
        "Callable": Callable,
        "TotalDischargeFlowParityAgileSmartExportManager": _TotalDischargeBase,
        "IntelligentDispatchObservabilityAgileSmartExportManager": _ObservabilityBase,
        "SimulationConfig": _SimulationConfig,
        "_reconcile_future_total_discharge_flow": lambda _state: None,
        "_rebase_display_soc": lambda _state, **_kwargs: None,
        "_reconcile_completed_settled_soc": lambda _state, **_kwargs: 0,
        "_reconcile_completed_from_persisted_decisions": reconcile_from_decisions,
        "_dt": lambda value: datetime.fromisoformat(value) if value else None,
    }
    module = ast.Module(body=[cls], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, ACTIVE.as_posix(), "exec"), namespace)
    return namespace["ActiveElapsedSocContinuityAgileSmartExportManager"]


def _live_morning_decisions() -> list[dict[str, Any]]:
    """Mirror the post-overnight 06:30 decision cadence seen in live evidence."""
    return [
        {
            "timestamp": "2026-09-02T06:30:34+01:00",
            "status": "PASS — shadow candidate ready",
            "target": {
                "charge_kw": 0.0,
                "battery_to_home_kw": 0.6,
                "battery_export_kw": 1.0,
                "total_discharge_kw": 1.6,
            },
            "safety_passed": True,
            "parity_passed": True,
        },
        {
            "timestamp": "2026-09-02T06:31:46+01:00",
            "status": "PASS — shadow candidate ready",
            "target": {
                "charge_kw": 0.0,
                "battery_to_home_kw": 0.7,
                "battery_export_kw": 0.8,
                "total_discharge_kw": 1.5,
            },
            "safety_passed": True,
            "parity_passed": True,
        },
        {
            "timestamp": "2026-09-02T06:32:58+01:00",
            "status": "PASS — shadow candidate ready",
            "target": {
                "charge_kw": 0.0,
                "battery_to_home_kw": 0.545,
                "battery_export_kw": 1.033,
                "total_discharge_kw": 1.578,
            },
            "safety_passed": True,
            "parity_passed": True,
        },
    ]


def test_publish_consumes_recorder_provider_when_manager_has_no_local_history() -> None:
    capture: dict[str, Any] = {}
    manager_type = _manager_class(capture)
    manager = manager_type.__new__(manager_type)
    manager._rolling_config = _SimulationConfig()
    assert not hasattr(manager, "_agile_decisions")

    recorder = type("Recorder", (), {})()
    recorder._agile_decisions = _live_morning_decisions()
    manager.bind_persisted_agile_decision_provider(
        lambda: getattr(recorder, "_agile_decisions", [])
    )
    state = {
        "current_routing_snapshot": {
            "generated_at": "2026-09-02T06:32:58+01:00",
        },
        "completed_flow_soc_continuity": {
            "active": True,
            "applied": False,
            "reason": "active elapsed battery energy unavailable",
            "reporting_only": True,
            "hardware_writes": "blocked",
        },
    }

    _ObservabilityBase.published = False
    manager._publish(state)

    assert state["completed_flow_soc_continuity"]["applied"] is True
    assert (
        state["completed_flow_soc_continuity"]["canonical_decision_provider_bound"]
        is True
    )
    assert (
        state["completed_flow_soc_continuity"]["canonical_decision_history_source"]
        == "ShadowValidationRecorder persisted Agile decisions"
    )
    assert capture["decisions"] == recorder._agile_decisions
    assert capture["decisions"] is not recorder._agile_decisions
    assert _ObservabilityBase.published is True
    assert not hasattr(manager, "_agile_decisions")


def test_provider_failure_is_read_only_and_fails_closed() -> None:
    capture: dict[str, Any] = {}
    manager_type = _manager_class(capture)
    manager = manager_type.__new__(manager_type)

    def broken_provider() -> list[dict[str, Any]]:
        raise RuntimeError("simulated recorder read failure")

    manager.bind_persisted_agile_decision_provider(broken_provider)
    decisions, source = manager._persisted_agile_decision_history()
    assert decisions == []
    assert source == "ShadowValidationRecorder provider unavailable"
    assert not hasattr(manager, "_agile_decisions")


def test_coordinator_binds_the_actual_shadow_recorder_history() -> None:
    coordinator = COORDINATOR.read_text(encoding="utf-8")
    assert "bind_persisted_agile_decision_provider" in coordinator
    assert 'getattr(self._shadow_validation, "_agile_decisions", [])' in coordinator

    alpha723 = ALPHA723.read_text(encoding="utf-8")
    active = ACTIVE.read_text(encoding="utf-8")
    assert "self._agile_decisions = decisions" in alpha723
    assert "self._agile_decisions = decisions[-MAX_AGILE_DECISIONS:]" in alpha723
    assert "self._persisted_agile_decision_provider = provider" in active
    assert "self._agile_decisions =" not in active
    assert "services.async_call" not in active
    assert "async_call(" not in active


def test_alpha871_is_reporting_only_and_keeps_platform_coordination() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )

    assert manifest["version"] == "0.8.0-alpha8.71"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert "ShadowValidationRecorder" in bundle["maintenance"]["reason"]
    assert "reporting-only" in bundle["maintenance"]["reason"]
