"""Alpha9.125: expensive what-if comparisons never gate live FoxESS control."""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import get_ident
from time import perf_counter

from kems_core.scenario_report_gate import ScenarioReportGate

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
NOW = datetime(2026, 10, 23, 7, 0, tzinfo=UTC)


def test_scenario_reporting_throttled_and_nonoverlapping() -> None:
    gate = ScenarioReportGate[str]()
    assert gate.claim(NOW, detailed=True)
    assert not gate.claim(NOW + timedelta(seconds=1), detailed=True)
    gate.complete("comparison-1", now=NOW, detailed=True)
    assert gate.cached(NOW + timedelta(seconds=90), detailed=True) == "comparison-1"
    assert not gate.claim(NOW + timedelta(seconds=299), detailed=True)
    assert gate.claim(NOW + timedelta(seconds=300), detailed=True)
    assert not gate.claim(NOW + timedelta(seconds=301), detailed=True)
    assert gate.cached(NOW + timedelta(seconds=301), detailed=True) == "comparison-1"
    gate.complete("comparison-2", now=NOW + timedelta(seconds=300), detailed=True)
    assert gate.cached(NOW + timedelta(seconds=301), detailed=True) == "comparison-2"


def test_reporting_mode_change_requires_new_report_never_reuses_wrong_mode() -> None:
    gate = ScenarioReportGate[str]()
    assert gate.claim(NOW, detailed=True)
    gate.complete("full", now=NOW, detailed=True)
    assert gate.cached(NOW, detailed=False) is None
    assert gate.claim(NOW + timedelta(seconds=1), detailed=False)
    # Previous valid detailed result remains available only in that mode.
    assert gate.cached(NOW, detailed=True) == "full"
    assert gate.cached(NOW, detailed=False) is None
    gate.complete("baseline", now=NOW + timedelta(seconds=2), detailed=False)
    assert gate.cached(NOW, detailed=False) == "baseline"
    assert not gate.claim(NOW + timedelta(seconds=5), detailed=False)


def test_midnight_cannot_reuse_yesterday_reporting_as_today() -> None:
    gate = ScenarioReportGate[str]()
    evening = datetime(2026, 10, 22, 23, 59, tzinfo=UTC)
    assert gate.claim(evening, detailed=True)
    gate.complete("yesterday", now=evening, detailed=True)
    midnight = evening + timedelta(minutes=2)
    assert gate.cached(midnight, detailed=True) is None
    assert gate.claim(midnight, detailed=True)


def test_late_executor_completion_never_mislabels_yesterday_as_today() -> None:
    gate = ScenarioReportGate[str]()
    evening = datetime(2026, 10, 22, 23, 59, tzinfo=UTC)
    assert gate.claim(evening, detailed=True)
    morning = evening + timedelta(minutes=3)
    gate.complete("previous-day-replay", now=morning, detailed=True)
    assert gate.cached(morning, detailed=True) is None
    assert gate.claim(morning, detailed=True)


def test_failed_executor_job_keeps_valid_report_and_throttles_retry() -> None:
    gate = ScenarioReportGate[str]()
    assert gate.claim(NOW, detailed=True)
    gate.complete("last-good", now=NOW, detailed=True)
    retry = NOW + timedelta(minutes=5)
    assert gate.claim(retry, detailed=True)
    gate.fail(RuntimeError("optional analysis failed"))
    assert gate.cached(retry, detailed=True) == "last-good"
    assert gate.status["last_error"] == "optional analysis failed"
    assert not gate.claim(retry + timedelta(seconds=2), detailed=True)
    assert gate.claim(retry + timedelta(minutes=5), detailed=True)


def test_executor_could_run_reporting_while_event_loop_continues() -> None:
    """The comparison may block its own worker, not Home Assistant's loop."""
    from threading import Event

    async def prove() -> None:
        worker_entered = Event()
        release_worker = Event()
        loop_thread = get_ident()

        def slow_report() -> tuple[int, int]:
            worker_entered.set()
            release_worker.wait(timeout=1.0)
            return get_ident(), 7

        pending = asyncio.create_task(asyncio.to_thread(slow_report))
        try:
            for _ in range(100):
                if worker_entered.is_set():
                    break
                await asyncio.sleep(0.001)
            assert worker_entered.is_set()
            tick = perf_counter()
            await asyncio.sleep(0.005)
            assert not pending.done()
            assert perf_counter() - tick < 0.2
        finally:
            release_worker.set()
        thread_id, value = await pending
        assert thread_id != loop_thread
        assert value == 7

    asyncio.run(prove())


def test_coordinator_never_calls_scenario_compare_inline_in_refresh() -> None:
    coordinator = ast.parse((ROOT / "coordinator.py").read_text())
    klass = next(
        node
        for node in coordinator.body
        if isinstance(node, ast.ClassDef) and node.name == "KEMSCoordinator"
    )
    scan = next(
        node
        for node in klass.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_update_data"
    )
    called = [
        node
        for node in ast.walk(scan)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"compare", "baseline_only"}
    ]
    assert not called
    separate = next(
        node
        for node in klass.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_async_refresh_scenario_reporting"
    )
    assert "async_add_executor_job" in ast.unparse(separate)
    assert "async_create_task" in ast.unparse(scan)
    assert "_foxess_control.async_update" in ast.unparse(scan)


def test_performance_telemetry_is_read_only_not_hardware_authority() -> None:
    coord = (ROOT / "coordinator.py").read_text()
    diagnostics = (ROOT / "diagnostics.py").read_text()
    assert 'checkpoint("agile_rolling_price_optimisation")' in coord
    assert 'checkpoint("commissioning_foxess_and_ev_actions")' in coord
    assert (
        '"coordinator_performance": coordinator.coordinator_performance_state'
        in diagnostics
    )
    assert '"recent_slow_scans": list(self._coordinator_slow_scans)' in coord
