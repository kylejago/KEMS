"""Alpha9.154: nonblocking history durability and physical-only solar evidence."""

from __future__ import annotations

import ast
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path
from threading import get_ident
from time import perf_counter
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


class FakeStore:
    saved = None

    @classmethod
    def __class_getitem__(cls, _item):
        return cls

    def __init__(self, *_args):
        self.writes = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.fail_once = False
        FakeStore.saved = self

    async def async_load(self):
        return self.writes[-1] if self.writes else None

    async def async_save(self, data):
        self.started.set()
        await self.release.wait()
        if self.fail_once:
            self.fail_once = False
            raise OSError("simulated disk failure")
        self.writes.append(data)


class FakeHass:
    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)

    async def async_add_executor_job(self, function, *args):
        return await asyncio.to_thread(function, *args)


class FakeSnapshot:
    thread_ids = []

    def __init__(self, timestamp, power=1.0):
        self.timestamp = timestamp
        self.power = power

    def to_dict(self):
        self.thread_ids.append(get_ident())
        return {"timestamp": self.timestamp.isoformat(), "power": self.power}

    @classmethod
    def from_dict(cls, item):
        return cls(datetime.fromisoformat(item["timestamp"]), item["power"])


def _history():
    module = ast.parse((KEMS / "history.py").read_text())
    node = next(
        item
        for item in module.body
        if isinstance(item, ast.ClassDef) and item.name == "HistoryRecorder"
    )
    namespace = {
        "Any": Any,
        "HomeAssistant": FakeHass,
        "Store": FakeStore,
        "Snapshot": FakeSnapshot,
        "timedelta": timedelta,
        "perf_counter": perf_counter,
        "asyncio": asyncio,
        "_LOGGER": logging.getLogger(__name__),
        "STORAGE_VERSION": 1,
        "SAVE_EVERY_RECORDS": 3,
        "DEFAULT_RECORD_INTERVAL_SECONDS": 300,
        "DOMAIN": "kems",
        "STORAGE_NAMESPACE": "records",
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
            "<history>",
            "exec",
        ),
        namespace,
    )
    return namespace["HistoryRecorder"]


def test_15_minute_checkpoint_does_not_block_next_control_decision() -> None:
    async def exercise():
        recorder = _history()(FakeHass(), "entry", 90)
        store = FakeStore.saved
        store.release.clear()
        start = datetime(2026, 10, 28, 12, tzinfo=UTC)
        for i in range(3):
            assert await recorder.async_record(
                FakeSnapshot(start + timedelta(minutes=5 * i))
            )
        assert recorder.status["pending_records"] == 3
        await asyncio.wait_for(store.started.wait(), 1)
        assert recorder.status["checkpoint_in_flight"]
        assert not store.writes
        # The scan must not await the delayed storage; the fourth observation
        # and the next control-phase tick still run.
        begin = perf_counter()
        assert await recorder.async_record(FakeSnapshot(start + timedelta(minutes=15)))
        await asyncio.sleep(0)
        assert perf_counter() - begin < 0.2
        assert recorder.status["pending_records"] >= 4
        store.release.set()
        await recorder.async_save()
        assert (
            store.writes[-1]["records"][-1]["timestamp"]
            == (start + timedelta(minutes=15)).isoformat()
        )
        assert recorder.status["pending_records"] == 0
        assert recorder.status["checkpoint_failures"] == 0
        assert recorder.status["checkpoint_count"] >= 2
        assert recorder.status["last_serialize_worker_seconds"] >= 0
        assert recorder.status["last_store_await_seconds"] >= 0
        assert recorder.status["last_checkpoint_total_seconds"] >= 0
        assert all(t != get_ident() for t in FakeSnapshot.thread_ids)

    FakeSnapshot.thread_ids = []
    asyncio.run(exercise())


def test_checkpoint_failure_preserves_unsaved_samples_until_flush() -> None:
    async def exercise():
        recorder = _history()(FakeHass(), "entry", 90)
        store = FakeStore.saved
        store.fail_once = True
        start = datetime(2026, 10, 28, 12, tzinfo=UTC)
        for i in range(3):
            await recorder.async_record(FakeSnapshot(start + timedelta(minutes=i * 5)))
        await asyncio.sleep(0.05)
        assert recorder.status["checkpoint_failures"] == 1
        assert recorder.status["pending_records"] == 3
        await recorder.async_save()
        assert recorder.status["pending_records"] == 0
        assert len(store.writes) == 1
        assert len(store.writes[0]["records"]) == 3

    asyncio.run(exercise())


def test_history_respects_sampling_and_prunes_after_restart() -> None:
    async def exercise():
        recorder = _history()(FakeHass(), "entry", 1)
        start = datetime(2026, 10, 28, 12, tzinfo=UTC)
        assert await recorder.async_record(FakeSnapshot(start))
        assert not await recorder.async_record(
            FakeSnapshot(start + timedelta(seconds=1))
        )
        assert await recorder.async_record(FakeSnapshot(start + timedelta(days=2)))
        await recorder.async_save()
        assert len(FakeStore.saved.writes[-1]["records"]) == 1
        assert (
            FakeStore.saved.writes[-1]["records"][0]["timestamp"]
            == (start + timedelta(days=2)).isoformat()
        )

    asyncio.run(exercise())


def _solar_flow():
    source = ast.parse((KEMS / "solar_routing_shadow.py").read_text())
    methods = {"_num", "_physical_solar_flow"}
    module = ast.Module(
        body=[
            node
            for node in source.body
            if isinstance(node, ast.FunctionDef) and node.name in methods
        ],
        type_ignores=[],
    )
    ns = {"Any": Any, "isfinite": isfinite}
    exec(compile(ast.fix_missing_locations(module), "<solar>", "exec"), ns)
    return ns["_physical_solar_flow"]


def _snapshot(**extra):
    payload = {
        "solar_power_kw": 3.224,
        "house_load_kw": 0.931,
        "battery_power_kw": -2.298,
        "grid_import_kw": 0.019,
        "grid_export_kw": 0.0,
        "ev_connected": False,
        "source_age_seconds": {
            "solar_power_kw": 4,
            "house_load_kw": 4,
            "battery_power_kw": 4,
            "grid_import_kw": 4,
            "grid_export_kw": 54,
        },
    }
    payload.update(extra)
    return SimpleNamespace(**payload)


def test_solar_display_reports_measured_grid_and_bounded_charge() -> None:
    result = _solar_flow()(_snapshot())
    assert result["status"] == "bounded_physical_inference"
    assert result["estimated_pv_to_battery_kw"] == 2.293
    assert result["measured_battery_charging_kw"] == 2.298
    assert result["measured_total_grid_export_kw"] == 0
    assert result["metered_pv_to_grid_kw"] is None
    assert result["reporting_only"]
    assert result["hardware_writes"] == "forbidden"


def test_solar_inference_fails_closed_on_stale_grid_import_and_ev() -> None:
    helper = _solar_flow()
    stale = _snapshot(
        source_age_seconds={**_snapshot().source_age_seconds, "grid_export_kw": 200}
    )
    for case in (
        stale,
        _snapshot(grid_import_kw=1.0),
        _snapshot(ev_connected=True),
        _snapshot(house_load_kw=10.0),
        _snapshot(solar_power_kw=None),
    ):
        assert helper(case)["estimated_pv_to_battery_kw"] is None


def test_dashboard_and_diagnostics_never_confuse_twin_with_physical_flow() -> None:
    dashboard = (ROOT / "dashboards/kems_master_dashboard.yaml").read_text()
    assert dashboard == (KEMS / "kems_master_dashboard.yaml").read_text()
    assert "Solar → site" in dashboard
    assert "PV → battery (bounded estimate)" in dashboard
    assert "solar-only export is **not** separately metered" in dashboard
    assert "sensor.kems_solar_routing_shadow" in dashboard
    shadow = (KEMS / "solar_routing_shadow.py").read_text()
    assert '"physical_solar_flow": _physical_solar_flow(snapshot)' in shadow
    assert '"reporting_only": True' in shadow
    coordinator = (KEMS / "coordinator.py").read_text()
    assert "await self._history.async_record(snapshot)" in coordinator
    assert "guard_paid_agile_physical_export(" in coordinator
    assert "await self._foxess_control.async_update(" in coordinator
    diagnostics = (KEMS / "diagnostics.py").read_text()
    assert '"history_persistence": coordinator.history_persistence_state' in diagnostics
    assert "live_control_waits_for_checkpoint" in (KEMS / "history.py").read_text()


def test_release_identity_and_unchanged_hardware_versions() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())
    assert manifest["version"] == "0.9.0-alpha9.154"
    assert bundle["maintenance"]["reason"].startswith("Alpha9.154:")
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.4"
