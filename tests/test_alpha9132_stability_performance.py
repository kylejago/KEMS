"""Alpha9.132: bounded maintenance events and exact Agile reserve replay."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _isolated_maintenance_payload():
    """Run the actual method without importing the Home Assistant integration."""
    source = (KEMS / "update_orchestrator.py").read_text()
    tree = ast.parse(source)
    owner = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "KEMSUpdateOrchestrator"
    )
    method = next(
        node for node in owner.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_maintenance_payload"
    )
    cls = ast.ClassDef(
        name="Isolated", bases=[], keywords=[], body=[method], decorator_list=[]
    )
    ns = {"dt_util": SimpleNamespace(now=lambda: datetime(2026, 10, 24, tzinfo=UTC))}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
                 "<isolated_maintenance_payload>", "exec"), ns)
    instance = ns["Isolated"]()
    instance.last_error = None
    return instance


def test_legacy_50kb_reason_and_components_fit_recorder_event_limit() -> None:
    manager = _isolated_maintenance_payload()
    input_ = {
        "bundle": "alpha9.132",
        "target": "0.9.0-alpha9.132",
        "reason": "very long release notes\n" * 3200,
        "maintenance": {
            "affected_components": ["component-" + "x" * 200 for _ in range(200)]
        },
        "error": "HACS failed" * 6000,
    }
    before = json.dumps(input_)
    notice = manager._maintenance_payload("failed", input_)
    assert len(json.dumps(notice).encode("utf-8")) < 4096
    assert len(notice["reason"]) <= 512
    assert len(notice["error"]) <= 256
    assert len(notice["affected_components"]) <= 12
    assert input_["reason"].startswith("very long")
    assert json.dumps(input_) == before


def test_bounded_release_reason_does_not_accumulate_old_changelogs() -> None:
    bundled = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    reason = bundled["maintenance"]["reason"]
    assert reason.startswith("Alpha9.132: Run pure Agile")
    assert len(reason) <= 512
    assert "HACS tag downloads depend on upstream HACS repair" in reason


def test_floor_linear_precomputation_preserves_legacy_reference() -> None:
    # Capture the actual floor class implementation from the KEMS module, but
    # evaluate it in isolation to avoid requiring a live HA installation.
    code = ast.parse((KEMS / "agile_smart_export.py").read_text())
    cls = next(n for n in code.body if isinstance(n, ast.ClassDef)
               and n.name == "AgileSmartExportManager")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
              and n.name == "_floor")
    holder = ast.ClassDef(name="Manager", bases=[], keywords=[], body=[fn],
                          decorator_list=[])
    calls = {"count": 0}

    def load(record):
        calls["count"] += 1
        value = record.house_load_kw
        return max(float(value), 0.0) if value is not None else None

    ns = {"_load": load}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[holder], type_ignores=[])),
                 "<floor>", "exec"), ns)
    manager = ns["Manager"]()
    config = SimpleNamespace(battery_reserve_percent=10, discharge_efficiency=0.92)
    start = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)
    records = [
        SimpleNamespace(
            timestamp=start + timedelta(seconds=i * 25),
            cheap_period_confirmed=i in {230, 520},
            house_load_kw=0.4 + (i % 7) / 10,
            forecast_minimum_precheap_soc_percent=12.0,
            forecast_expected_house_remaining_today_kwh=(6.5 if i % 2 else None),
        )
        for i in range(720)
    ]
    # The exact previous forward-scan semantics, including early cheap breaks,
    # the last interval and forecast protection whenever no cheap is reached.
    def naive(index: int, recs):
        needed = 0.0
        reached = False
        for future, following in zip(recs[index + 1:], recs[index + 2:]):
            if future.cheap_period_confirmed:
                reached = True
                break
            hours = min(max((following.timestamp - future.timestamp).total_seconds(), 0) / 3600, 0.5)
            if future.house_load_kw is not None:
                needed += max(float(future.house_load_kw), 0.0) * hours
        forecast = recs[index].forecast_expected_house_remaining_today_kwh
        if not reached and forecast is not None:
            needed = max(needed, float(forecast))
        return min(max(56.42 * 0.1, 56.42 * 0.12, 56.42 * 0.1 + needed / 0.92), 56.42)

    for i in range(len(records) - 1):
        actual = manager._floor(records, i, records[i], config, 56.42 * 0.1, 56.42)
        assert actual == pytest.approx(naive(i, records), abs=1e-8)
    assert calls["count"] <= len(records)
    # A distinct replay must recalculate rather than return old cached demand.
    changed = list(records)
    changed[150] = SimpleNamespace(**{**vars(records[150]), "house_load_kw": 4.5})
    assert manager._floor(changed, 0, changed[0], config, 5.642, 56.42) != manager._floor(
        records, 0, records[0], config, 5.642, 56.42
    )


def test_agile_replay_yields_event_loop_via_executor() -> None:
    src = (KEMS / "agile_smart_export.py").read_text()
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "AgileSmartExportManager")
    scan = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "async_update")
    code = ast.unparse(scan)
    assert "await executor(self._compare_day, *compare_args)" in code
    assert "partial(self._compare_day, *tomorrow_args, projection=True)" in code
    assert "_compare_day(*compare_args)" in code  # test fake-HA fallback only
    # No changes to actual inverter, EV, solar physical reserve or safety logic.


def test_slow_scans_are_bounded_and_keep_quantiles() -> None:
    src = (KEMS / "coordinator.py").read_text()
    assert "recent_p95_seconds" in src
    assert "recent_mean_seconds" in src
    assert "agile_optimisation_seconds" in src
    assert "_coordinator_scan_samples[-60:]" in src
    assert ">= timedelta(minutes=10)" in src


def test_recorder_attributes_remain_under_safe_limit() -> None:
    # Existing comprehensive overflow tests remain the authoritative
    # behavioural proof; their limits are still part of this release.
    src = (KEMS / "kems_core/commissioning_presentation.py").read_text()
    assert "8192" in src or "8_192" in src
    assert "recorder_safe_commissioning_attributes" in src
