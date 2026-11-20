"""Alpha9.239: bounded Happy Hour sample processing and publication attribution."""

from __future__ import annotations

import ast
import importlib
import math
import random
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
START = datetime(2026, 11, 20, 12, tzinfo=UTC)


def _load_observed():
    parent = sys.modules.setdefault(
        "custom_components", types.ModuleType("custom_components")
    )
    parent.__path__ = [str(ROOT.parent)]
    package = sys.modules.setdefault(
        "custom_components.kems", types.ModuleType("custom_components.kems")
    )
    package.__path__ = [str(ROOT)]
    return importlib.import_module("custom_components.kems.happy_hour_observed_flow")


def _reference_integrate(records, *, start, end, field, sign=0):
    """Original full-list implementation: immutable parity oracle."""
    mod = _load_observed()
    samples = []
    for item in records:
        timestamp = mod._dt(getattr(item, "timestamp", None))
        value = mod._value(item, field)
        if timestamp is None or value is None:
            continue
        if sign == -1:
            value = max(-value, 0.0)
        elif sign == 1:
            value = max(value, 0.0)
        else:
            value = max(value, 0.0)
        samples.append((timestamp, value))
    samples.sort()
    seed = next((sample for sample in reversed(samples) if sample[0] <= start), None)
    if seed is None or start - seed[0] > mod._MAX_GAP:
        return 0.0, False
    cursor, power = start, seed[1]
    energy = 0.0
    for at, new_power in samples:
        if at <= start or at <= cursor:
            continue
        if at > end:
            break
        if at - cursor > mod._MAX_GAP:
            return 0.0, False
        energy += power * (at - cursor).total_seconds() / 3600.0
        cursor, power = at, new_power
    if end - cursor > mod._MAX_GAP:
        return 0.0, False
    return energy + power * (end - cursor).total_seconds() / 3600.0, True


def _record(minutes, value, **extra):
    return SimpleNamespace(
        timestamp=START + timedelta(minutes=minutes),
        battery_power_kw=value,
        grid_import_kw=abs(value),
        **extra,
    )


def test_window_bound_sample_filter_identical_for_unordered_duplicate_ages():
    rng = random.Random(9239)
    start = START
    end = START + timedelta(minutes=30)
    records = [
        _record(-5, 2.0),
        _record(0, -4.0),
        _record(5, -3.0),
        _record(5, 3.0),
        _record(10, 4.0),
        _record(15, float("nan")),
        _record(20, 2.0),
        _record(25, 0.0),
        _record(30, -2.0),
        _record(35, 10.0),
        _record(10_000, 1000.0),
        SimpleNamespace(timestamp=None, battery_power_kw=5.0),
        SimpleNamespace(timestamp="bad-timestamp", battery_power_kw=5.0),
    ]
    for _ in range(30):
        rng.shuffle(records)
        for sign in (-1, 0, 1):
            for field in ("battery_power_kw", "grid_import_kw"):
                old = _reference_integrate(
                    records, start=start, end=end, field=field, sign=sign
                )
                new = _load_observed()._integrate(
                    records, start=start, end=end, field=field, sign=sign
                )
                assert new == old


def test_window_bound_filter_parity_for_long_future_tail_and_gap_fail_closed():
    old = _reference_integrate
    new = _load_observed()._integrate
    future = [_record(120 + i, float(i % 9)) for i in range(2200)]
    readings = [_record(-5, 2.0), _record(0, 2.0), _record(5, 3.0)]
    for rows in (readings + future, future + readings, future):
        for sign in (-1, 0, 1):
            assert new(
                rows,
                start=START,
                end=START + timedelta(minutes=30),
                field="battery_power_kw",
                sign=sign,
            ) == old(
                rows,
                start=START,
                end=START + timedelta(minutes=30),
                field="battery_power_kw",
                sign=sign,
            )


def test_profile_helper_is_read_only_and_bounded_to_a_scan():
    source = (ROOT / "agile_smart_export_runtime_base.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_record_agile_publication_phase"
    )
    scope = {"Any": object, "perf_counter": perf_counter}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
            "<profile-helper>",
            "exec",
        ),
        scope,
    )
    record = scope["_record_agile_publication_phase"]
    owner = SimpleNamespace(_kems_agile_publication_profile={})
    record(owner, "routing", perf_counter() - 0.1)
    record(owner, "routing", perf_counter() - 0.2)
    assert owner._kems_agile_publication_profile["routing"]["calls"] == 2
    assert math.isfinite(owner._kems_agile_publication_profile["routing"]["seconds"])
    assert owner._kems_agile_publication_profile["routing"]["seconds"] >= 0.299
    other = SimpleNamespace()
    record(other, "routing", perf_counter() - 1.0)
    assert not hasattr(other, "_kems_agile_publication_profile")


def test_full_publish_and_physical_control_order_remains_original():
    flow = (ROOT / "agile_flow_presentation.py").read_text(encoding="utf-8")
    canonical = (ROOT / "agile_canonical_flow_accounting.py").read_text(
        encoding="utf-8"
    )
    solar = (ROOT / "agile_live_solar_soc_continuity.py").read_text(encoding="utf-8")
    coordinator = (ROOT / "coordinator.py").read_text(encoding="utf-8")
    runtime = (ROOT / "agile_smart_export_runtime_base.py").read_text(encoding="utf-8")
    rolling = (ROOT / "agile_rolling_replan_runtime.py").read_text(encoding="utf-8")
    for layer in (flow, canonical, solar):
        assert "self._publish(self._state)" in layer
        assert "self._kems_suppress_identical_base_publication = True" in layer
    assert "_ORIGINAL_RUNTIME_PUBLISH(self, state)" in rolling
    assert "super()._publish(state)" in runtime
    assert "overlay_completed_happy_hour_flow(" in runtime
    assert "overlay_booked_happy_hour_flow(" in runtime
    assert coordinator.index("await self._agile_smart_export.async_update(") < (
        coordinator.index("settled_before_shadow = settled_half_hour_snapshot(")
    )
    assert 'detail_seconds[f"agile_publish_{phase}_seconds"]' in coordinator
    assert "foxess_control = await self._foxess_control.async_update(" in coordinator
