"""Alpha9.157 — settlement timing must never change settlement or dispatch."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, thread_time
from types import SimpleNamespace
from typing import Any

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"


def _isolate_settlement_manager(applied: bool):
    source = ast.parse((KEMS / "agile_current_day_settlement.py").read_text())
    manager = next(
        node
        for node in source.body
        if isinstance(node, ast.ClassDef)
        and node.name == "SettledCurrentDayAgileSmartExportManager"
    )
    method = next(
        node
        for node in manager.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "reconcile_current_day_settlements"
    )
    isolated = ast.ClassDef(
        name="Isolated", bases=[], keywords=[], body=[method], decorator_list=[]
    )
    calls: list[str] = []

    def reconcile(state, settled, now, **kwargs):
        del settled, now, kwargs
        diagnostic = {"applied": applied, "accounting_checks": {"correct": True}}
        state["current_day_settlement_reconciliation"] = diagnostic
        calls.append("reconcile")
        return diagnostic

    def refresh(manager, **kwargs):
        del kwargs
        assert manager._panel_config is None
        calls.append("handoff")
        return {
            "tomorrow_compare_seconds": 0.004,
            "tomorrow_compare_thread_cpu_seconds": 0.003,
            "second_publication_seconds": 0.006,
            "second_publication_thread_cpu_seconds": 0.005,
        }

    ns = {
        "Any": Any,
        "perf_counter": perf_counter,
        "thread_time": thread_time,
        "reconcile_current_day_settlements": reconcile,
        "refresh_tomorrow_handoff_from_settled_soc": refresh,
        "_number": lambda value: value,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[isolated], type_ignores=[])),
            "<isolated-settlement>",
            "exec",
        ),
        ns,
    )

    class Runtime(ns["Isolated"]):
        def __init__(self):
            self._state = {
                "today_slots": [],
                "rolling_export_plan": {"available": True},
            }
            self._rolling_config = SimpleNamespace(
                battery_capacity_kwh=30.0, discharge_efficiency=0.9
            )
            self._panel_config = "panel"

        @property
        def state(self):
            return dict(self._state)

        def _publish(self, state):
            assert self._panel_config is None
            assert state is self._state
            calls.append("publish")

    return Runtime(), calls


def test_live_settlement_publishes_and_handoff_stays_authoritative() -> None:
    manager, calls = _isolate_settlement_manager(True)
    before = dict(manager._state)
    result = manager.reconcile_current_day_settlements(
        settled_half_hours=[{"slot": "2026-10-29T01:00:00+00:00"}],
        now=datetime(2026, 10, 29, 7, 35, tzinfo=UTC),
    )
    assert calls == ["reconcile", "publish", "handoff"]
    assert manager._panel_config == "panel"
    assert result["today_slots"] == before["today_slots"]
    detail = result["current_day_settlement_reconciliation"]["performance"]
    assert detail["settlement_math_seconds"] >= 0
    assert detail["first_publication_seconds"] >= 0
    assert detail["tomorrow_handoff_seconds"] >= 0
    assert detail["tomorrow_compare_seconds"] == 0.004
    assert detail["second_publication_seconds"] == 0.006
    assert detail["total_seconds"] >= 0
    assert detail["scope"] == "read_only_reporting_no_hardware_writes"


def test_unapplied_settlement_does_not_publish_or_refresh() -> None:
    manager, calls = _isolate_settlement_manager(False)
    result = manager.reconcile_current_day_settlements(
        settled_half_hours=[], now=datetime(2026, 10, 29, tzinfo=UTC)
    )
    assert calls == ["reconcile"]
    assert manager._panel_config == "panel"
    detail = result["current_day_settlement_reconciliation"]["performance"]
    assert detail["first_publication_seconds"] == 0.0
    assert detail["tomorrow_handoff_seconds"] == 0.0
    assert detail["second_publication_seconds"] == 0.0


def test_same_scan_corrected_settlement_and_tomorrow_change_guards_remain() -> None:
    coordinator = (KEMS / "coordinator.py").read_text()
    handoff = (KEMS / "agile_settled_soc_handoff.py").read_text()
    assert "if post_shadow_settlement_changed:" in coordinator
    assert "settled_half_hours_changed(" in coordinator
    assert "if second_publication_needed:" in handoff
    assert "prior_tomorrow_period" in handoff
    assert 'prior_tomorrow_slots != state["tomorrow_slots"]' in handoff
    assert "manager._publish(manager._state)" in handoff
    for name in ("precontrol_", "postshadow_", "agile_manager_wrapper_seconds"):
        assert name in coordinator
    for name in ("tomorrow_compare_seconds", "second_publication_seconds"):
        assert name in handoff
