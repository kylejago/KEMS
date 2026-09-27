"""Read-only, persisted EV transition trace contracts."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from kems_core import Snapshot

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"
NOW = datetime(2026, 9, 27, 20, 0, tzinfo=UTC)


def _load_trace_module():
    package = ModuleType("kems_ev_trace_test")
    package.__path__ = [str(KEMS)]
    fake_ha = ModuleType("homeassistant")
    fake_ha.__path__ = []
    fake_core = ModuleType("homeassistant.core")
    fake_core.HomeAssistant = type("HomeAssistant", (), {})
    fake_helpers = ModuleType("homeassistant.helpers")
    fake_helpers.__path__ = []
    fake_storage = ModuleType("homeassistant.helpers.storage")

    class FakeStore:
        saved = {}

        def __init__(self, _hass, _version, key):
            self.key = key

        async def async_load(self):
            return self.saved.get(self.key)

        async def async_save(self, value):
            self.saved[self.key] = value

    fake_storage.Store = FakeStore
    fake_const = ModuleType("kems_ev_trace_test.const")
    fake_const.DOMAIN = "kems"
    fake_const.STORAGE_NAMESPACE = "kems_test"
    import kems_core

    spec = importlib.util.spec_from_file_location(
        "kems_ev_trace_test.ev_charge_trace", KEMS / "ev_charge_trace.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    modules = {
        "kems_ev_trace_test": package,
        "kems_ev_trace_test.const": fake_const,
        "kems_ev_trace_test.kems_core": kems_core,
        "kems_ev_trace_test.kems_core.models": sys.modules["kems_core.models"],
        "homeassistant": fake_ha,
        "homeassistant.core": fake_core,
        "homeassistant.helpers": fake_helpers,
        "homeassistant.helpers.storage": fake_storage,
    }
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module, FakeStore


def _snapshot(minutes=0, *, connected=False, charging=False, cheap=False):
    return Snapshot(
        timestamp=NOW + timedelta(minutes=minutes),
        ev_connected=connected,
        ev_charging=charging,
        ev_power_kw=6.7 if charging else 0.0,
        ev_power_age_seconds=8.0,
        house_load_kw=7.7 if charging else 1.0,
        solar_power_kw=0.0,
        battery_power_kw=1.0,
        battery_soc=60.0,
        grid_import_kw=6.7 if charging else 0.0,
        grid_export_kw=0.0,
        off_peak=cheap,
        source_age_seconds={"house_load_kw": 8.0},
        shared_bus_ev_audit={"status": "net_allocation_consistent"},
    )


def test_event_trace_preserves_ohme_foxess_and_actual_readback_provenance():
    module, _ = _load_trace_module()
    sample = module.build_ev_trace_sample(
        _snapshot(connected=True, charging=True, cheap=True),
        event="charge_start",
        foxess_control={"decision_action": "self_use", "commands_permitted": True},
        command_shadow={
            "entity_binding": {
                "status": "PASS",
                "entities": {
                    "work_mode": {
                        "normalised_observation": "Self Use",
                        "observation_source": "sensor_readback",
                        "status": "PASS",
                    }
                },
            }
        },
    )
    assert sample["ev_power_kw"] == 6.7
    assert sample["battery_soc"] == 60.0
    assert sample["cheap_period_confirmed"] is True
    assert sample["foxess_readback"]["work_mode"]["value"] == "Self Use"
    assert sample["foxess_readback"]["work_mode"]["source"] == "sensor_readback"
    assert sample["existing_live_control"]["decision_action"] == "self_use"
    assert sample["new_ev_routing_hardware_authorised"] is False


def test_plug_charge_stop_and_slot_edges_are_retained_across_restart():
    module, _ = _load_trace_module()
    recorder = module.EVChargeTraceRecorder(object(), "sample")
    async def exercise():
        await recorder.async_load()
        await recorder.async_record(_snapshot())
        await recorder.async_record(_snapshot(1))
        await recorder.async_record(_snapshot(2, connected=True))
        await recorder.async_record(_snapshot(3, connected=True, cheap=True))
        await recorder.async_record(
            _snapshot(4, connected=True, charging=True, cheap=True)
        )
        await recorder.async_record(
            _snapshot(5, connected=True, charging=True, cheap=True)
        )
        await recorder.async_record(_snapshot(6, connected=True, cheap=True))
        await recorder.async_record(_snapshot(7, connected=False, cheap=True))
        await recorder.async_save()
        recovered = module.EVChargeTraceRecorder(object(), "sample")
        await recovered.async_load()
        return recovered.state

    result = asyncio.run(exercise())
    events = [item["event"] for item in result["samples"]]
    assert "plugged" in events
    assert "cheap_slot_transition" in events
    assert "charge_start" in events
    assert "charge_stop" in events
    assert "unplugged" in events
    assert result["sample_count"] >= 7
    assert result["new_ev_routing_hardware_authorised"] is False


def test_trace_fails_safe_when_not_installed_or_ev_data_missing():
    module, _ = _load_trace_module()
    rec = module.EVChargeTraceRecorder(object(), "another")
    assert rec.wants_capture(_snapshot()) is False
    assert rec.wants_capture(_snapshot(connected=True)) is True
    assert rec.wants_capture(_snapshot(charging=True)) is True
    source = (KEMS / "ev_charge_trace.py").read_text(encoding="utf-8")
    assert "number.set_value" not in source
    assert "select.select_option" not in source
    assert "async_call(" not in source
    coordinator = (KEMS / "coordinator.py").read_text(encoding="utf-8")
    assert "await self._ev_charge_trace.async_record(" in coordinator
    assert "await self._ev_charge_trace.async_load()" in coordinator
    assert "await self._ev_charge_trace.async_save()" in coordinator
    diagnostics = (KEMS / "diagnostics.py").read_text(encoding="utf-8")
    assert '"ev_charge_trace": coordinator.ev_charge_trace_state' in diagnostics
