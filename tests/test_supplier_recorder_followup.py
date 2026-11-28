"""Exercise the bounded recorder paths without needing a live HA database."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from kems_core import supplier_charges, supplier_intervals

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"
NOW = datetime(2026, 11, 27, 15, tzinfo=UTC)


def _load_recorder_module():
    package = ModuleType("kems_supplier_recorder_test")
    package.__path__ = [str(KEMS)]
    fake_ha = ModuleType("homeassistant")
    fake_ha.__path__ = []
    fake_core = ModuleType("homeassistant.core")
    fake_core.HomeAssistant = object
    fake_helpers = ModuleType("homeassistant.helpers")
    fake_helpers.__path__ = []
    fake_registry = ModuleType("homeassistant.helpers.entity_registry")
    fake_storage = ModuleType("homeassistant.helpers.storage")

    class FakeStore:
        def __init__(self, *_args):
            self.saved = None

        async def async_save(self, value):
            self.saved = value

    fake_storage.Store = FakeStore
    fake_const = ModuleType("kems_supplier_recorder_test.const")
    fake_const.DOMAIN = "kems"
    fake_const.STORAGE_NAMESPACE = "kems_test"
    fake_providers = ModuleType("kems_supplier_recorder_test.providers")
    fake_providers.__path__ = []
    fake_map = ModuleType("kems_supplier_recorder_test.providers.entity_map")
    fake_map.KEMSEntities = object
    spec = importlib.util.spec_from_file_location(
        "kems_supplier_recorder_test.supplier_interval_recorder",
        KEMS / "supplier_interval_recorder.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    modules = {
        "kems_supplier_recorder_test": package,
        "kems_supplier_recorder_test.const": fake_const,
        "kems_supplier_recorder_test.kems_core": sys.modules["kems_core"],
        "kems_supplier_recorder_test.kems_core.supplier_charges": supplier_charges,
        "kems_supplier_recorder_test.kems_core.supplier_intervals": (
            supplier_intervals
        ),
        "kems_supplier_recorder_test.providers": fake_providers,
        "kems_supplier_recorder_test.providers.entity_map": fake_map,
        "homeassistant": fake_ha,
        "homeassistant.core": fake_core,
        "homeassistant.helpers": fake_helpers,
        "homeassistant.helpers.entity_registry": fake_registry,
        "homeassistant.helpers.storage": fake_storage,
    }
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


def _state(attrs):
    return SimpleNamespace(state="1", attributes=attrs)


def test_baseline_capture_runs_between_slow_supplier_scans():
    module = _load_recorder_module()
    end = NOW + timedelta(hours=1)
    middle = NOW + timedelta(minutes=30)
    states = {
        "event": _state(
            {
                "joined_events": [
                    {
                        "id": "9019",
                        "start": NOW.isoformat(),
                        "end": end.isoformat(),
                        "octopoints_per_kwh": 136,
                    }
                ]
            }
        )
    }
    entities = SimpleNamespace(
        saving_session_events="event",
        saving_session_import_baseline="import",
        saving_session_export_baseline="export",
    )

    def baseline(left, right, value):
        return _state(
            {
                "baselines": [
                    {
                        "start": left.isoformat(),
                        "end": right.isoformat(),
                        "baseline": value,
                        "is_incomplete_calculation": False,
                    }
                ]
            }
        )

    async def exercise():
        recorder = module.SupplierIntervalRecorder(
            SimpleNamespace(states=states), "test"
        )
        # Suppress the slower interval scan; no registry or file access.
        recorder._next_at = end + timedelta(minutes=30)
        states["import"] = baseline(NOW, middle, 0.25)
        states["export"] = baseline(NOW, middle, 0.5)
        await recorder.async_observe(NOW, entities)
        retained = recorder._late_events["9019"]
        assert retained["import_baseline_kwh"] is None
        assert retained["import_baseline_rows"] == {NOW.isoformat(): 0.25}
        states["import"] = baseline(middle, end, 0.75)
        states["export"] = baseline(middle, end, 1.0)
        await recorder.async_observe(NOW + timedelta(minutes=1), entities)
        retained = recorder._late_events["9019"]
        assert retained["import_baseline_kwh"] == 1.0
        assert retained["export_baseline_kwh"] == 1.5
        assert recorder._store.saved["late_power_down_evidence"]["9019"] == (retained)
        assert recorder._next_at == end + timedelta(minutes=30)
        assert (
            recorder.status["power_down_baseline_capture"]["joined_event_observations"][
                0
            ]["import"]["accepted_half_hours"]
            == 1
        )

    asyncio.run(exercise())


def test_history_batches_use_fixed_anchor_and_skip_empty_window():
    module = _load_recorder_module()
    queries = []
    start = NOW - timedelta(days=1)
    rows = [
        {
            "kind": "electricity_import",
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=30)).isoformat(),
            "kwh": 1.0,
            "charge_pence": 6.6,
        }
    ]

    class FakeHass:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

        def async_create_background_task(self, coroutine, _name):
            return asyncio.create_task(coroutine)

    async def exercise():
        recorder = module.SupplierIntervalRecorder(FakeHass(), "test")

        async def read(entities, left, right):
            queries.append((entities, left, right))
            return rows if len(queries) == 1 else []

        recorder._recover_recorded_charges = read
        entities = {"sensor.import_cost": "electricity_import"}
        assert not await recorder._consume_recorded_charges(NOW, entities)
        await recorder._history_task
        assert await recorder._consume_recorded_charges(
            NOW + timedelta(minutes=30), entities
        )
        await recorder._history_task
        assert not await recorder._consume_recorded_charges(
            NOW + timedelta(hours=1), entities
        )
        assert queries == [
            (entities, NOW - timedelta(days=7), NOW),
            (entities, NOW - timedelta(days=14), NOW - timedelta(days=7)),
        ]
        assert recorder.status["historical_charge_recovery"]["empty_batches"] == 1
        assert recorder.status["historical_charge_recovery"]["candidate_rows"] == 1
        assert len(recorder._charges.rows) == 1
        for batch in range(2, 12):
            await recorder._history_task
            await recorder._consume_recorded_charges(
                NOW + timedelta(hours=batch), entities
            )
        assert recorder._history_task is None
        assert len(queries) == 12
        assert recorder.status["historical_charge_recovery"]["stop_reason"] == (
            "batch_limit"
        )

    asyncio.run(exercise())


def test_complete_price_coverage_stops_and_new_gap_reopens_history():
    module = _load_recorder_module()

    class FakeHass:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

        def async_create_background_task(self, coroutine, _name):
            return asyncio.create_task(coroutine)

    async def exercise():
        recorder = module.SupplierIntervalRecorder(FakeHass(), "test")
        entities = {
            "sensor.import_cost": "electricity_import",
            "sensor.export_cost": "electricity_export",
        }
        start = NOW.replace(hour=0) - timedelta(days=1)
        rows = []
        for kind in entities.values():
            for n in range(48):
                left = start + timedelta(minutes=30 * n)
                rows.append(
                    {
                        "kind": kind,
                        "start": left.isoformat(),
                        "end": (left + timedelta(minutes=30)).isoformat(),
                        "kwh": 1.0,
                        "charge_pence": 6.6,
                    }
                )
        recorder._ledger.ingest(rows, source="octopus_csv", now=NOW)
        recorder._charges.ingest(rows, source="octopus_csv", now=NOW)
        queries = []

        async def read(entities, left, right):
            queries.append((entities, left, right))
            return []

        recorder._recover_recorded_charges = read
        await recorder._consume_recorded_charges(
            NOW, entities, commissioning_date="2026-11-24"
        )
        assert recorder._history_task is None
        assert recorder.status["historical_charge_recovery"]["stop_reason"] == (
            "all_retained_complete_days_priced"
        )
        assert not queries
        recorder._charges.ingest(
            [{**rows[0], "charge_pence": 7.6}],
            source="octopus_integration",
            now=NOW,
        )
        await recorder._consume_recorded_charges(
            NOW + timedelta(minutes=30), entities, commissioning_date="2026-11-24"
        )
        assert recorder._history_task is not None
        await recorder._history_task
        assert len(queries) == 1

    asyncio.run(exercise())
