"""Alpha9.132: Recorder, Agile and scheduler performance regressions."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _isolated_method(source: str, owner: str, method: str, names: dict):
    tree = ast.parse((KEMS / source).read_text())
    target = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == owner
    )
    fn = next(
        node
        for node in target.body
        if isinstance(node, ast.FunctionDef) and node.name == method
    )
    wrapper = ast.ClassDef(
        name="Isolated", bases=[], keywords=[], body=[fn], decorator_list=[]
    )
    code = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
    namespace = dict(names)
    exec(compile(code, "<isolated>", "exec"), namespace)
    return namespace["Isolated"]()


def test_enormous_legacy_reason_and_event_data_are_bounded() -> None:
    instance = _isolated_method(
        "update_orchestrator.py",
        "KEMSUpdateOrchestrator",
        "_maintenance_payload",
        {
            "Any": Any,
            "dt_util": SimpleNamespace(now=lambda: datetime(2026, 10, 24, tzinfo=UTC)),
        },
    )
    instance.last_error = None
    legacy = {
        "target": "0.9.0-alpha9.135",
        "reason": "release notes " * 5000,
        "error": "HACS failed " * 5000,
        "maintenance": {"affected_components": ["a" * 200] * 400},
    }
    before = json.dumps(legacy)
    event = instance._maintenance_payload("failed", legacy)
    assert len(json.dumps(event).encode()) < 4096
    assert len(event["reason"]) <= 512
    assert len(event["error"]) <= 256
    assert len(event["affected_components"]) <= 12
    updater = (KEMS / "update_orchestrator.py").read_text()
    assert 'error = notice.get("error") or reason' in updater
    assert json.dumps(legacy) == before


def test_release_note_no_longer_embeds_old_changelog() -> None:
    release = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    assert release["maintenance"]["reason"].startswith("Alpha9.135:")
    assert (
        "Alpha9.131: Fix misleading shadow recorder" in release["maintenance"]["reason"]
    )


def test_floor_matches_original_lookahead_and_uses_linear_load_reads() -> None:
    observed = {"reads": 0}

    def read(record):
        observed["reads"] += 1
        return record.house_load_kw

    manager = _isolated_method(
        "agile_smart_export.py",
        "AgileSmartExportManager",
        "_floor",
        {"Snapshot": object, "SimulationConfig": object, "_load": read},
    )
    config = SimpleNamespace(battery_reserve_percent=10, discharge_efficiency=0.92)
    start = datetime(2026, 10, 24, tzinfo=UTC)
    records = [
        SimpleNamespace(
            timestamp=start + timedelta(seconds=25 * i),
            cheap_period_confirmed=i in (230, 520),
            house_load_kw=0.4 + (i % 7) / 10,
            forecast_minimum_precheap_soc_percent=12.0,
            forecast_expected_house_remaining_today_kwh=6.5 if i % 2 else None,
        )
        for i in range(720)
    ]

    def old_floor(index, sequence):
        demand = 0.0
        reached_cheap = False
        for future, following in zip(
            sequence[index + 1 :], sequence[index + 2 :], strict=False
        ):
            if future.cheap_period_confirmed:
                reached_cheap = True
                break
            hours = min(
                max((following.timestamp - future.timestamp).total_seconds(), 0) / 3600,
                0.5,
            )
            if future.house_load_kw is not None:
                demand += max(float(future.house_load_kw), 0.0) * hours
        forecast = sequence[index].forecast_expected_house_remaining_today_kwh
        if not reached_cheap and forecast is not None:
            demand = max(demand, forecast)
        reserve = 5.642
        return min(max(reserve, 56.42 * 0.12, reserve + demand / 0.92), 56.42)

    for i in range(719):
        result = manager._floor(records, i, records[i], config, 5.642, 56.42)
        assert result == pytest.approx(old_floor(i, records), abs=1e-8)
    assert observed["reads"] <= len(records)

    altered = list(records)
    altered[150] = SimpleNamespace(**{**vars(records[150]), "house_load_kw": 5.0})
    assert manager._floor(altered, 0, altered[0], config, 5.642, 56.42) != (
        manager._floor(records, 0, records[0], config, 5.642, 56.42)
    )


def test_agile_numeric_replay_is_executor_offloaded() -> None:
    source = (KEMS / "agile_smart_export.py").read_text()
    assert "await executor(self._compare_day, *compare_args)" in source
    assert "partial(self._compare_day, *tomorrow_args, projection=True)" in source
    assert "result = self._compare_day(*compare_args)" in source


def test_scan_performance_retains_bounded_timing_history() -> None:
    source = (KEMS / "coordinator.py").read_text()
    for field in (
        "recent_p95_seconds",
        "recent_mean_seconds",
        "recent_max_seconds",
        "agile_optimisation_seconds",
        "_coordinator_scan_samples[-60:]",
        ">= timedelta(minutes=10)",
    ):
        assert field in source


def test_commissioning_recorder_projection_keeps_small_limit() -> None:
    source = (KEMS / "kems_core/commissioning_presentation.py").read_text()
    assert "8_192" in source
    assert "recorder_safe_commissioning_attributes" in source
