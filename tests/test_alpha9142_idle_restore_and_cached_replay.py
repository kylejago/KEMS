"""Alpha9.142: pending FoxESS restore and historical cache fast-path regressions."""
from __future__ import annotations

import ast
from datetime import date
from math import isfinite
from pathlib import Path

import pytest
from kems_core.agile_historical_replay_cache import HistoricalReplayCache

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


def _predicate():
    source = (ROOT / "foxess_control_backend.py").read_text()
    fn = next(
        n for n in ast.parse(source).body
        if isinstance(n, ast.FunctionDef) and n.name == "_idle_pending_restore_safe"
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            fn,
        ],
        type_ignores=[],
    )
    ns = {"_number": lambda v: float(v) if v is not None and isfinite(float(v)) else None}
    exec(compile(ast.fix_missing_locations(module), "<idle-gate>", "exec"), ns)
    return ns["_idle_pending_restore_safe"]


def _safe():
    return dict(
        pending=True, owned=True, last_action="self_use",
        commands_permitted=True, decision_action="self_use",
        requested_export_kw=0.0, cheap_period_confirmed=False,
        commissioning_export_test=False, ev_hold_active=False,
        happy_hour_active=False, power_down_active=False,
    )


def test_idle_restore_gate_rejects_any_active_safety_or_energy_workflow():
    gate = _predicate()
    assert gate(**_safe())
    for key, change in (
        ("pending", False), ("owned", False),
        ("last_action", "force_discharge"), ("last_action", "force_charge"),
        ("commands_permitted", False), ("decision_action", "force_discharge"),
        ("decision_action", "force_charge"), ("requested_export_kw", 1.0),
        ("requested_export_kw", None), ("requested_export_kw", float("nan")),
        ("cheap_period_confirmed", True),
        ("commissioning_export_test", True), ("ev_hold_active", True),
        ("happy_hour_active", True), ("power_down_active", True),
    ):
        assert not gate(**{**_safe(), key: change}), key


def test_idle_restore_still_requires_real_separate_physical_readback():
    code = (ROOT / "foxess_control_backend.py").read_text()
    guard = (ROOT / "update_maintenance_guard.py").read_text()
    assert "elif _idle_pending_restore_safe(" in code
    assert "restored = await self._async_restore(" in code
    assert "verify_physical_baseline=True," in code
    assert "and not _commissioning_restore_readback_matches(" in code
    assert "FoxESS control restoration pending" in guard


def test_historical_cache_hit_returns_independent_result_without_replay():
    cache = HistoricalReplayCache()
    d, now = date(2026, 10, 25), date(2026, 10, 26)
    inputs = (("battery", 15.0), ("price", 20.0), "config")
    original = cache.evaluate(
        day=d, today=now, projection=False, inputs=inputs,
        calculate=lambda: {"slot_plan": [{"kwh": 2.0}]},
    )
    value = cache.get_cached(day=d, today=now, projection=False, inputs=inputs)
    assert value == original
    value["slot_plan"][0]["kwh"] = 99
    assert cache.get_cached(day=d, today=now, projection=False, inputs=inputs)["slot_plan"][0]["kwh"] == 2.0
    assert cache.status["hits"] == 2
    assert cache.status["misses"] == 1


@pytest.mark.parametrize("inputs", [
    (("battery", 14.0), ("price", 20.0), "config"),
    (("battery", 15.0), ("price", 21.0), "config"),
    (("battery", 15.0), ("price", 20.0), "changed config"),
    (("battery", 15.0, "late sample"), ("price", 20.0), "config"),
])
def test_changed_history_inputs_recalculate(inputs):
    cache = HistoricalReplayCache()
    d, now = date(2026, 10, 25), date(2026, 10, 26)
    original = (("battery", 15.0), ("price", 20.0), "config")
    cache.evaluate(day=d, today=now, projection=False, inputs=original, calculate=lambda: {"old": True})
    assert cache.get_cached(day=d, today=now, projection=False, inputs=inputs) is None
    result = cache.evaluate(day=d, today=now, projection=False, inputs=inputs, calculate=lambda: {"new": True})
    assert result == {"new": True}


def test_live_and_tomorrow_never_serve_cached_values():
    cache = HistoricalReplayCache()
    old, today = date(2026, 10, 25), date(2026, 10, 26)
    cache.evaluate(day=old, today=today, projection=False, inputs=("x",), calculate=lambda: {"cached": True})
    for day, current, projection in (
        (today, today, False), (date(2026, 10, 27), today, True),
        (old, None, False), (old, today, True),
    ):
        assert cache.get_cached(day=day, today=current, projection=projection, inputs=("x",)) is None


def test_per_scan_rolling_and_live_hardware_paths_remain_unchanged():
    source = (ROOT / "agile_smart_export.py").read_text()
    runtime = (ROOT / "agile_smart_export_runtime_base.py").read_text()
    rolling = (ROOT / "agile_rolling_replan_runtime.py").read_text()
    coordinator = (ROOT / "coordinator.py").read_text()
    assert "cached_result = (" in source
    assert "await executor(self._compare_day, *compare_args)" in source
    assert "_historical_cached_comparison" in runtime
    assert "runtime.ANALYSIS_REFRESH = timedelta(0)" in rolling
    assert "await self._agile_smart_export.async_update(" in coordinator
    assert "await self._foxess_control.async_update(" in coordinator
