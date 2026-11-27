"""Read-only, persisted EV transition trace contracts."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
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
    from kems_core import shared_bus_balance

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
        "kems_ev_trace_test.kems_core.shared_bus_balance": shared_bus_balance,
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


def test_cheap_ev_charge_trace_records_plan_and_flags_discharge_without_writes():
    module, _ = _load_trace_module()
    base = _snapshot(connected=True, charging=True, cheap=True)
    charging = replace(
        base, ev_power_kw=7.558, battery_power_kw=-4.7, grid_import_kw=13.5
    )
    plan = SimpleNamespace(
        desired_charge_power_kw=4.7,
        ev_grid_guard_status="ev_battery_hold_grid_charging",
        site_import_limit_kw=14.5,
        site_import_headroom_kw=1.0,
    )
    sample = module.build_ev_trace_sample(
        charging, event="charge_start", planned_control=plan
    )
    audit = sample["ev_cheap_charge_cap_audit"]
    assert audit["confirmed_cheap_ev_charging"] is True
    assert audit["desired_battery_charge_power_kw"] == 4.7
    assert audit["charge_cap_kw_when_ev_charging"] == 5.0
    assert audit["site_import_headroom_kw"] == 1.0
    assert audit["battery_discharging_during_ev_charge"] is False
    assert audit["cap_target_exceeded"] is False
    assert audit["reporting_only"] is True
    reversed_power = replace(charging, battery_power_kw=7.56)
    sample = module.build_ev_trace_sample(
        reversed_power, event="scan", planned_control=plan
    )
    assert (
        sample["ev_cheap_charge_cap_audit"]["battery_discharging_during_ev_charge"]
        is True
    )
    assert sample["new_ev_routing_hardware_authorised"] is False


def test_cheap_ev_charge_trace_summary_persists_violations_across_restart():
    module, _ = _load_trace_module()
    recorder = module.EVChargeTraceRecorder(object(), "charge-audit")
    plan = SimpleNamespace(
        desired_charge_power_kw=4.5,
        ev_grid_guard_status="ev_battery_hold_grid_charging",
        site_import_limit_kw=14.5,
        site_import_headroom_kw=0.9,
    )

    async def exercise():
        healthy = replace(
            _snapshot(connected=True, charging=True, cheap=True),
            battery_power_kw=-4.5,
        )
        await recorder.async_record(healthy, planned_control=plan)
        spike = replace(
            _snapshot(1, connected=True, charging=True, cheap=True),
            battery_power_kw=7.56,
        )
        await recorder.async_record(spike, planned_control=plan)
        await recorder.async_save()
        resumed = module.EVChargeTraceRecorder(object(), "charge-audit")
        await resumed.async_load()
        return resumed.state["ev_cheap_charge_cap_summary"]

    summary = asyncio.run(exercise())
    assert summary["confirmed_cheap_ev_samples"] == 2
    assert summary["unexpected_battery_discharge_samples"] == 1
    assert summary["charge_target_above_5kw_samples"] == 0
    assert summary["samples_missing_planned_target"] == 0
    assert summary["status"] == "unexpected_battery_discharge_observed"
    assert summary["independent_ev_isolation_proven"] is False


def test_unconfirmed_daytime_ohme_charging_never_claims_cheap_charge_cap():
    module, _ = _load_trace_module()
    sample = module.build_ev_trace_sample(
        _snapshot(connected=True, charging=True, cheap=False),
        event="charge_start",
        planned_control=SimpleNamespace(desired_charge_power_kw=7.0),
    )
    audit = sample["ev_cheap_charge_cap_audit"]
    assert audit["confirmed_cheap_ev_charging"] is False
    assert audit["charge_cap_kw_when_ev_charging"] is None
    assert audit["cap_target_exceeded"] is False
    assert sample["extra_slot_house_routing_candidate"]["status"] == (
        "hold_fallback_required"
    )


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
    assert "ev_trace = dict(coordinator.ev_charge_trace_state)" in diagnostics
    assert 'ev_trace["samples"] = ev_trace_samples[-64:]' in diagnostics
    assert '"ev_charge_trace": ev_trace' in diagnostics


def test_cheap_charge_exception_survives_regular_trace_rollover_and_restart():
    module, _ = _load_trace_module()
    module.MAX_RECORDS = 3
    recorder = module.EVChargeTraceRecorder(object(), "exception_rollover")

    async def exercise():
        await recorder.async_record(
            _snapshot(connected=True, charging=True, cheap=True)
        )
        for minute in range(1, 6):
            await recorder.async_record(
                replace(
                    _snapshot(minute, connected=True, charging=True, cheap=True),
                    battery_power_kw=-4.0,
                )
            )
        await recorder.async_save()
        recovered = module.EVChargeTraceRecorder(object(), "exception_rollover")
        await recovered.async_load()
        return recovered.state

    state = asyncio.run(exercise())
    assert len(state["samples"]) == 3
    assert len(state["exception_samples"]) == 1
    exception = state["exception_samples"][0]
    assert exception["timestamp"] == NOW.isoformat()
    assert exception["battery_power_kw"] == 1.0
    assert state["new_ev_routing_hardware_authorised"] is False


def test_outside_cheap_grid_shortfall_is_retained_without_tariff_authority():
    module, _ = _load_trace_module()
    recorder = module.EVChargeTraceRecorder(object(), "extra_slot_risk")

    async def exercise():
        await recorder.async_record(
            replace(
                _snapshot(connected=True, charging=True),
                battery_power_kw=7.6,
                grid_import_kw=3.0,
            )
        )
        recovered = module.EVChargeTraceRecorder(object(), "extra_slot_risk")
        await recovered.async_load()
        return recovered.state

    state = asyncio.run(exercise())
    assert state["outside_cheap_ev_risk_samples_retained"] == 1
    sample = state["exception_samples"][0]
    assert sample["outside_cheap_ev_startup_risk"] is True
    assert sample["cheap_period_confirmed"] is False
    assert sample["new_ev_routing_hardware_authorised"] is False


def test_discharge_context_distinguishes_post_sample_command_readback():
    module, _ = _load_trace_module()
    row = {
        "timestamp": NOW.isoformat(),
        "ev_cheap_charge_cap_audit": {"battery_discharging_during_ev_charge": True},
        "existing_live_control": {
            "decision_action": "force_charge",
            "last_write_at": (NOW + timedelta(seconds=4)).isoformat(),
        },
        "foxess_readback": {"work_mode": {"value": "Force Charge"}},
    }
    audit = module._discharge_exception_context([row, {}])
    assert audit["samples"] == 1
    assert audit["command_written_after_physical_sample"] == 1
    assert audit["control_action_counts"] == {"force_charge": 1}
    assert audit["persistent_discharge_proven"] is False
    assert audit["hardware_write_authorised"] is False


def test_extra_slot_cost_estimates_only_qualified_adjacent_samples():
    module, _ = _load_trace_module()
    policy = {"estimated_ev_only_discount_candidate": True}
    ages = {
        field: 8.0
        for field in (
            "grid_import_kw",
            "grid_export_kw",
            "battery_power_kw",
            "solar_power_kw",
        )
    }
    snap = replace(
        _snapshot(connected=True, charging=True),
        battery_power_kw=-0.03,
        current_import_rate=35.88,
        next_import_rate=6.6,
        intelligent_slot_evidence={"effective_fallback_offpeak_rate_pence": 6.6},
        source_age_seconds=ages,
        tariff_source_age_seconds={
            "current_import_rate": 8,
            "next_import_rate": 8,
            "off_peak": 8,
        },
    )
    a = module.build_ev_trace_sample(
        snap, event="charge_start", extra_slot_policy=policy
    )
    b = module.build_ev_trace_sample(
        replace(snap, timestamp=NOW + timedelta(seconds=60)),
        event="scan",
        extra_slot_policy=policy,
    )
    result = module.summarise_extra_slot_cost([a, b])
    assert result["qualified_sample_interval_seconds"] == 60
    assert result["estimated_candidate_ev_kwh"] == 0.111667
    assert result["estimated_discount_pence"] == 3.2696
    assert result["supplier_discount_confirmed"] is False
    assert result["roi_or_ledger_write_authorised"] is False
    assert (
        module.extra_slot_cost_sample(snap, policy, reward_event_active=True)["status"]
        == "other_event_or_tariff"
    )
    assert (
        module.extra_slot_cost_sample(replace(snap, battery_power_kw=7.0), policy)[
            "status"
        ]
        == "ambiguous_grid_allocation"
    )
    assert (
        module.extra_slot_cost_sample(replace(snap, source_age_seconds={}), policy)[
            "status"
        ]
        == "stale_power"
    )
    assert module.extra_slot_cost_sample(snap, None)["status"] == "not_qualified"
    b["timestamp"] = (NOW + timedelta(minutes=2)).isoformat()
    assert module.summarise_extra_slot_cost([a, b])["estimated_candidate_ev_kwh"] == 0


def test_ev_cost_evidence_persists_and_never_bridges_restart():
    module, _ = _load_trace_module()
    policy = {"estimated_ev_only_discount_candidate": True}
    now = datetime.now(UTC).replace(minute=1, second=0, microsecond=0)
    snap = replace(
        _snapshot(connected=True, charging=True),
        timestamp=now,
        battery_power_kw=0.0,
        current_import_rate=35.88,
        next_import_rate=6.6,
        intelligent_slot_evidence={"effective_fallback_offpeak_rate_pence": 6.6},
        source_age_seconds={
            field: 8.0
            for field in (
                "grid_import_kw",
                "grid_export_kw",
                "battery_power_kw",
                "solar_power_kw",
            )
        },
        tariff_source_age_seconds={
            "current_import_rate": 8,
            "next_import_rate": 8,
            "off_peak": 8,
        },
    )

    async def exercise():
        recorder = module.EVChargeTraceRecorder(object(), "cost_evidence")
        await recorder.async_record(snap, extra_slot_policy=policy)
        await recorder.async_record(
            replace(snap, timestamp=now + timedelta(seconds=30)),
            extra_slot_policy=policy,
        )
        await recorder.async_save()
        before = recorder.state["extra_slot_cost_evidence"]
        assert before["qualified_sample_interval_seconds"] == 30
        assert before["retained_half_hours"] == 1

        # Restore with an explicit reference instant to avoid wall clock
        # dependence in this unit test.
        recovered = module.EVChargeTraceRecorder(object(), "cost_evidence")
        await recovered.async_load()
        recovered._cost_buckets = module._restore_cost_buckets(
            recorder._cost_buckets, now=now + timedelta(seconds=30)
        )
        await recovered.async_record(
            replace(snap, timestamp=now + timedelta(seconds=60)),
            extra_slot_policy=policy,
        )
        assert recovered.state["extra_slot_cost_evidence"][
            "qualified_sample_interval_seconds"
        ] == 30
        await recovered.async_record(
            replace(snap, timestamp=now + timedelta(seconds=90)),
            extra_slot_policy=policy,
        )
        assert recovered.state["extra_slot_cost_evidence"][
            "qualified_sample_interval_seconds"
        ] == 60
        # Repeated/reordered observations cannot accrue the same seconds.
        await recovered.async_record(
            replace(snap, timestamp=now + timedelta(seconds=60)),
            extra_slot_policy=policy,
        )
        await recovered.async_record(
            replace(snap, timestamp=now + timedelta(seconds=90)),
            extra_slot_policy=policy,
        )
        assert recovered.state["extra_slot_cost_evidence"][
            "qualified_sample_interval_seconds"
        ] == 60

    asyncio.run(exercise())
