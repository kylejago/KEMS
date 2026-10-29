"""Alpha9.152: keep observed SOC and performance evidence separate from control."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_observable_worker_elapsed_does_not_change_batched_replay_result() -> None:
    source = (KEMS / "agile_smart_export.py").read_text()
    klass = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.ClassDef) and node.name == "AgileSmartExportManager"
    )
    method = next(
        node
        for node in klass.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_timed_historical_comparison_batch"
    )
    module = ast.Module(body=[method], type_ignores=[])
    elapsed = iter([100.0, 100.123])
    ns = {"perf_counter": lambda: next(elapsed), "Any": object}
    exec(compile(ast.fix_missing_locations(module), "<timer>", "exec"), ns)
    fake = SimpleNamespace(
        _historical_comparison_batch=lambda *args: {"day": {"result": 42}}
    )
    data, duration = ns["_timed_historical_comparison_batch"](fake, "input")
    assert data == {"day": {"result": 42}}
    assert duration == 0.123


def test_historical_worker_and_executor_wait_are_recorded_separately() -> None:
    source = (KEMS / "agile_smart_export.py").read_text()
    assert "historical_batch_worker_seconds" in source
    assert "historical_batch_await_seconds" in source
    assert "historical_batch_wait_overhead_seconds" in source
    assert (
        "batched_results, historical_batch_worker_seconds = await executor(" in source
    )
    assert "self._timed_historical_comparison_batch" in source
    assert "historical_batch_executor_jobs = 1" in source
    assert "if day < today_date and day.isoformat() in batched_results:" in source
    assert "today = calculated.get(local_now.date().isoformat())" in source
    assert "tomorrow = await executor(" in source
    assert "historical_batch_wait_overhead_seconds" in source


def test_performance_timeline_preserves_overlapping_integrations_evidence() -> None:
    source = (KEMS / "coordinator.py").read_text()
    for marker in (
        "forecast_refresh",
        "history_record",
        "precontrol_settlement_reconciliation",
        "control_plan_and_event_overlays",
        "physical_export_reserve_guard",
        "ev_hold_and_export_commissioning",
        "shadow_recorder",
        "commissioning_foxess_and_ev_actions",
    ):
        assert marker in source
    assert '"slow_hourly": dict(self._coordinator_slow_hourly)' in source
    assert "if elapsed >= 10.0:" in source
    assert "max_seconds" in source
    assert "historical_batch_wait_overhead_seconds" in source
    assert "slowest stage" in source
    assert "self._coordinator_slow_scans[-12:]" in source
    # Safety and hardware writes remain their existing explicitly separate steps.
    assert "guard_paid_agile_physical_export(" in source
    assert "await self._foxess_control.async_update(" in source
    assert "cheap_period_confirmed=bool(snapshot.cheap_period_confirmed)" in source
    assert "confirmed-cheap Force Charge" in source


def test_dashboard_never_presents_overnight_projection_as_measured_soc() -> None:
    source = (ROOT / "dashboards" / "kems_master_dashboard.yaml").read_text()
    packaged = (KEMS / "kems_master_dashboard.yaml").read_text()
    assert source == packaged
    home = source.split("  - title: Live Data", 1)[0]
    kems = source.split("  - title: KEMS", 1)[1]
    assert "sensor.kems_simulated_" not in home
    assert "Battery reality vs planning" in kems
    assert "sensor.kems_battery_state_of_charge" in kems
    assert "sensor.kems_simulated_battery_state_of_charge" in kems
    assert "physical − advisory" in kems
    assert "Hypothetical next cheap-window SOC ceiling" in kems
    assert "counterfactual scenario" in kems
    assert "100% preference is a target" in kems
    assert "name: Next cheap-window model ceiling" in source
    assert "name: Overnight charge target" not in source


def test_release_does_not_force_panel_or_pi_update() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())
    assert manifest["version"] == "0.9.0-alpha9.159"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.4"
    assert bundle["components"]["property_web"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["pi_agent"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["maintenance"]["reason"].startswith("Alpha9.159:")
