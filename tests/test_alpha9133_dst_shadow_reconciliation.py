"""Alpha9.133: London DST charge capability and live/shadow status regressions."""

from __future__ import annotations

import ast
import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from kems_core.models import ControlState
from kems_core.shadow_validation import shadow_recorder_status
from kems_core.tomorrow_soc_handoff import (
    _cheap_window_hours,
    project_tomorrow_midnight_soc,
)

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
LONDON = ZoneInfo("Europe/London")


@pytest.mark.parametrize(
    ("local_day", "elapsed_hours", "final_soc"),
    [
        (datetime(2026, 10, 24, 11, 40, tzinfo=LONDON), 7.0, 97.506),
        (datetime(2027, 3, 27, 11, 40, tzinfo=LONDON), 5.0, 73.933),
        (datetime(2026, 11, 7, 11, 40, tzinfo=LONDON), 6.0, 85.720),
    ],
)
def test_elapsed_cheap_charge_hours_across_dst(
    local_day: datetime, elapsed_hours: float, final_soc: float
) -> None:
    midnight_soc, projection = project_tomorrow_midnight_soc(
        now=local_day,
        current_soc_percent=75.0,
        projected_precheap_soc_percent=15.0,
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
    )
    capability = projection["cheap_window_charge_capability"]
    assert capability["charge_hours_available"] == elapsed_hours
    assert capability["maximum_charge_input_kwh"] == pytest.approx(7.0 * elapsed_hours)
    assert capability["maximum_achievable_soc_percent"] == pytest.approx(
        final_soc, abs=0.002
    )
    assert capability["charge_target_physically_reachable"] is False
    assert projection["charge_hours_before_midnight"] == 0.5
    assert midnight_soc == 20.893
    assert projection["hardware_writes"] == "blocked"
    assert capability["hardware_writes"] == "blocked"
    assert (
        _cheap_window_hours(time(23, 30), time(5, 30), on_date=local_day.date())
        == elapsed_hours
    )


def test_active_pre_midnight_after_start_does_not_recharge_elapsed_minutes() -> None:
    _, projection = project_tomorrow_midnight_soc(
        now=datetime(2026, 10, 24, 23, 45, tzinfo=LONDON),
        current_soc_percent=20.0,
        projected_precheap_soc_percent=15.0,
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
    )
    assert projection["basis"] == "current SOC inside active cheap window"
    assert projection["starting_soc_percent"] == 20.0
    assert projection["charge_hours_before_midnight"] == 0.25
    assert (
        projection["cheap_window_charge_capability"]["charge_hours_available"] == 6.75
    )


def test_shadow_reporting_reconciles_only_after_live_backend_result() -> None:
    root = ast.parse((KEMS / "shadow_validation.py").read_text())
    cls = next(
        x
        for x in root.body
        if isinstance(x, ast.ClassDef) and x.name == "ShadowValidationRecorder"
    )
    method = next(
        x
        for x in cls.body
        if isinstance(x, ast.FunctionDef) and x.name == "sync_live_backend_status"
    )
    wrapper = ast.ClassDef(
        name="Recorder", bases=[], keywords=[], body=[method], decorator_list=[]
    )
    ns = {
        "ControlState": ControlState,
        "shadow_recorder_status": shadow_recorder_status,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
            "<shadow_sync>",
            "exec",
        ),
        ns,
    )
    rec = ns["Recorder"]()
    emitted = []
    rec._publish = lambda: emitted.append(dict(rec._state))
    rec._state = {
        "status": "Shadow comparison — live backend unavailable",
        "command_safety": {"passed": True},
        "ready_for_shadow": True,
        "hardware_writes": "blocked",
    }
    rec.sync_live_backend_status(
        control=ControlState(
            operating_mode="control",
            real_backend_available=True,
            commands_permitted=True,
            blocked_reason="Paid-export idle Self Use is inside the bounded live scope",
        ),
        emergency_stop=False,
    )
    assert rec._state["status"] == "Shadow comparison active — live control permitted"
    assert rec._state["live_backend_available"] is True
    assert rec._state["live_control_commands_permitted"] is True
    assert rec._state["hardware_writes"] == "blocked"
    assert len(emitted) == 1

    rec.sync_live_backend_status(
        control=ControlState(
            operating_mode="control",
            real_backend_available=True,
            commands_permitted=False,
        ),
        emergency_stop=False,
    )
    assert rec._state["status"] == "Shadow comparison — live controller not permitted"


def test_controller_run_order_does_not_move_hardware_or_settlement() -> None:
    coordinator = (KEMS / "coordinator.py").read_text()
    a = coordinator.index("await self._shadow_validation.async_update(")
    b = coordinator.index("self._agile_smart_export.reconcile_current_day_settlements(", a)
    c = coordinator.index("foxess_control = await self._foxess_control.async_update(")
    d = coordinator.index("self._shadow_validation.sync_live_backend_status(")
    assert a < b < c < d
    assert "agile_manager_update_seconds" in coordinator
    assert "agile_history_backfill_seconds" in coordinator


def test_release_version_and_read_only_scope() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    assert manifest["version"] == "0.9.0-alpha9.133"
    reason = bundle["maintenance"]["reason"]
    assert reason.startswith("Alpha9.133:")
    assert "Alpha9.132: Run pure Agile day replays" in reason
    assert "No live FoxESS" in reason
