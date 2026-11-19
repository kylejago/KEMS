"""Alpha9.233: physical Ohme EV charging reuses the existing MinSOC hold.

Regression inputs are from the owner's 19 Nov 2026 06:32-06:53 charge trace.
No supplier/Octopus Intelligent tariff fields are promoted by this trigger.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from kems_core import ControlConfig, ControlState, Snapshot
from kems_core.control_write_authority import (
    assess_foxess_control_write_authority,
    resolve_live_min_soc_on_grid,
    should_freeze_owned_ev_hold,
)
from kems_core.ev_grid_guard import (
    measured_ohme_ev_charge_active,
    protect_measured_ohme_ev_hold,
)

NOW = datetime(2026, 11, 19, 6, 32, 58, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "kems"


def _snapshot(**updates: object) -> Snapshot:
    values: dict[str, object] = {
        "timestamp": NOW,
        "off_peak": False,
        "intelligent_slot": False,
        "ev_connected": True,
        "ev_charging": True,
        "ev_power_kw": 3.038,
        "ev_power_age_seconds": 5.0,
        "battery_soc": 88.0,
        "battery_power_kw": 5.831,
        "grid_import_kw": 0.0,
        "house_load_kw": 5.623,
        "source_data_age_seconds": 5.0,
    }
    values.update(updates)
    return Snapshot(**values)


def _control(**updates: object) -> ControlState:
    values: dict[str, object] = {
        "operating_mode": "control",
        "operating_reason": "agile_rolling_price_optimised",
        "desired_work_mode": "Self Use",
        "desired_charge_power_kw": 0.0,
        "desired_min_soc_percent": 15.0,
        "desired_battery_to_home_power_kw": 5.6,
        "desired_total_discharge_power_kw": 5.6,
        "desired_battery_export_power_kw": 0.0,
        "desired_grid_export_allowed": True,
        "data_fresh": True,
        "plan_safe": True,
        "grid_available": True,
        "preflight_passed": 15,
        "preflight_total": 15,
    }
    values.update(updates)
    return ControlState(**values)


def _config(**updates: object) -> ControlConfig:
    values: dict[str, object] = {
        "operating_mode": "control",
        "commissioned": True,
        "control_enabled": True,
        "emergency_stop": False,
        "site_import_limit_kw": 14.5,
        "stale_data_seconds": 180,
    }
    values.update(updates)
    return ControlConfig(**values)


def _apply(snapshot=None, control=None, config=None, **kwargs):
    return protect_measured_ohme_ev_hold(
        snapshot or _snapshot(),
        control or _control(),
        config or _config(),
        eligible_for_hold_only=True,
        **kwargs,
    )


def test_0632_charge_battery_discharge_arms_existing_self_use_floor():
    snap = _snapshot()
    assert not snap.cheap_period_confirmed
    assert measured_ohme_ev_charge_active(snap)
    guarded = _apply(snap)
    assert guarded.ev_grid_guard_status == "ev_battery_hold_ohme_measured"
    assert guarded.desired_work_mode == "Self Use"
    assert guarded.desired_min_soc_percent == 89.0
    assert guarded.desired_charge_power_kw == 0.0
    assert guarded.desired_total_discharge_power_kw == 0.0
    assert guarded.desired_battery_to_home_power_kw == 0.0
    assert guarded.desired_battery_export_power_kw == 0.0
    assert guarded.desired_grid_export_allowed is False
    assert guarded.total_site_import_kw == 5.831
    assert guarded.site_import_headroom_kw == 8.669


def test_real_noncheap_hold_can_be_written_with_existing_verified_self_use():
    guarded = _apply()
    decision = assess_foxess_control_write_authority(
        guarded,
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=True,
        cheap_period_confirmed=False,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
    )
    assert decision.commands_permitted
    assert decision.action == "self_use"
    assert decision.force_charge_power_kw is None
    assert decision.force_discharge_power_kw is None
    assert (
        resolve_live_min_soc_on_grid(
            decision,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=10.0,
            pending_intelligent_ev_hold_active=True,
        )
        == 89.0
    )
    assert (
        resolve_live_min_soc_on_grid(
            decision,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=10.0,
            pending_intelligent_ev_hold_active=False,
        )
        == 10.0
    )


def test_0635_source_can_raise_but_never_chase_falling_soc_down():
    guarded = _apply(
        _snapshot(
            timestamp=NOW + timedelta(minutes=3),
            battery_soc=87,
            battery_power_kw=6.323,
            grid_import_kw=0.0,
            ev_power_kw=3.026,
        ),
        held_floor_percent=89.0,
    )
    assert guarded.desired_min_soc_percent == 89.0
    assert guarded.total_site_import_kw == 6.323


def test_ohme_power_and_charging_source_must_be_fresh_and_real():
    for changes in (
        {"ev_charging": False},
        {"ev_connected": False},
        {"ev_power_kw": 0.0},
        {"ev_power_kw": None},
        {"ev_power_age_seconds": None},
        {"ev_power_age_seconds": 91.0},
        {"stale_fields": ("ev_power_kw",)},
    ):
        snap = _snapshot(**changes)
        assert not measured_ohme_ev_charge_active(snap)
        assert _apply(snap) is not None
        assert _apply(snap).ev_grid_guard_status != "ev_battery_hold_ohme_measured"


def test_priorities_do_not_change_and_cheap_mode_unchanged():
    assert _apply(_snapshot(off_peak=True)) is not None
    for updates in (
        {"saving_session_active": True},
        {"ev_connected": False},
    ):
        assert _apply(_snapshot(**updates)).ev_grid_guard_status != (
            "ev_battery_hold_ohme_measured"
        )
    for updates in (
        {"desired_work_mode": "Force Discharge"},
        {"desired_battery_export_power_kw": 2.0},
        {"operating_mode": "shadow"},
        {"alpha969_routing_shadow_only": True},
        {"plan_safe": False},
        {"site_import_limit_exceeded": True},
    ):
        assert _apply(control=_control(**updates)).ev_grid_guard_status != (
            "ev_battery_hold_ohme_measured"
        )
    assert _apply(config=_config(emergency_stop=True)) is not None


def test_missing_physical_soc_and_site_headroom_never_approve_new_hold():
    assert _apply(_snapshot(battery_soc=None)).ev_grid_guard_status == (
        "observed_ohme_hold_blocked_no_fresh_soc"
    )
    assert _apply(_snapshot(source_data_age_seconds=181)).desired_min_soc_percent == 15
    assert _apply(_snapshot(grid_import_kw=None)).ev_grid_guard_status == (
        "observed_ohme_hold_blocked_site_unknown"
    )
    assert (
        _apply(
            _snapshot(grid_import_kw=9.0, battery_power_kw=6.323)
        ).ev_grid_guard_status
        == "observed_ohme_hold_blocked_site_limit"
    )


def test_ohme_hold_can_be_applied_when_mode_sensor_is_unavailable():
    # 19 Nov Ohme charge mode became unavailable after finishing; charger
    # status+power remains the source for a hold, not inferred tariff authority.
    snap = _snapshot(intelligent_slot_evidence={"ohme_charge_mode": None})
    assert measured_ohme_ev_charge_active(snap)
    assert _apply(snap).ev_grid_guard_status == "ev_battery_hold_ohme_measured"


def _session_module():
    package = ModuleType("kems_ohme_hold_test")
    package.__path__ = [str(ROOT)]
    core = ModuleType("kems_ohme_hold_test.kems_core")
    core.__path__ = [str(ROOT / "kems_core")]
    ha = ModuleType("homeassistant")
    ha.__path__ = []
    helpers = ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    storage = ModuleType("homeassistant.helpers.storage")

    class FakeStore:
        data = {}

        def __init__(self, _hass, _version, key):
            self.key = key

        async def async_load(self):
            return self.data.get(self.key)

        async def async_save(self, data):
            self.data[self.key] = data

    storage.Store = FakeStore
    const = ModuleType("kems_ohme_hold_test.const")
    const.DOMAIN = "kems"
    const.STORAGE_NAMESPACE = "kems_test"
    import kems_core.ev_grid_guard as ev_guard

    spec = importlib.util.spec_from_file_location(
        "kems_ohme_hold_test.ev_grid_hold_session",
        ROOT / "ev_grid_hold_session.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    modules = {
        "kems_ohme_hold_test": package,
        "kems_ohme_hold_test.const": const,
        "kems_ohme_hold_test.kems_core": core,
        "kems_ohme_hold_test.kems_core.ev_grid_guard": ev_guard,
        "homeassistant": ha,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.storage": storage,
    }
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module, FakeStore


def test_measured_charge_latches_pause_and_releases_on_finished_or_timeout():
    module, fake_store = _session_module()
    fake_store.data.clear()

    async def run():
        session = module.EVGridHoldSession(object(), "measured")
        first = await session.async_apply(
            _snapshot(), _control(), _config(), no_paid_export_mode=True
        )
        paused = await session.async_apply(
            _snapshot(
                timestamp=NOW + timedelta(seconds=60),
                ev_charging=False,
                ev_power_kw=0.0,
                battery_soc=87.0,
            ),
            _control(),
            _config(),
            no_paid_export_mode=True,
        )
        ended = await session.async_apply(
            _snapshot(
                timestamp=NOW + timedelta(seconds=70),
                ev_charging=False,
                ev_power_kw=0.0,
            ),
            _control(),
            _config(),
            no_paid_export_mode=True,
            ohme_finished=True,
        )
        resumed = await session.async_apply(
            _snapshot(timestamp=NOW + timedelta(minutes=3), battery_soc=86),
            _control(),
            _config(),
            no_paid_export_mode=True,
        )
        timeout = await session.async_apply(
            _snapshot(
                timestamp=NOW + timedelta(minutes=6),
                ev_charging=False,
                ev_power_kw=0,
            ),
            _control(),
            _config(),
            no_paid_export_mode=True,
        )
        return first, paused, ended, resumed, timeout, session.status

    first, paused, ended, resumed, timeout, status = asyncio.run(run())
    assert first.ev_grid_guard_status == "ev_battery_hold_ohme_measured"
    assert paused.ev_grid_guard_status == "ev_battery_hold_ohme_brief_pause"
    assert paused.desired_min_soc_percent == 89.0
    assert ended.ev_grid_guard_status == "inactive"
    assert resumed.desired_min_soc_percent == 87.0
    assert timeout.ev_grid_guard_status == "inactive"
    assert status["observed_ohme_hold_active"] is False


def test_transient_missing_ohme_readback_freezes_only_verified_existing_floor():
    module, fake_store = _session_module()
    fake_store.data.clear()

    async def run():
        session = module.EVGridHoldSession(object(), "ohme-dropout")
        first = await session.async_apply(
            _snapshot(), _control(), _config(), no_paid_export_mode=True
        )
        uncertain = await session.async_apply(
            _snapshot(
                timestamp=NOW + timedelta(seconds=30),
                ev_charging=None,
                ev_power_kw=None,
            ),
            _control(),
            _config(),
            no_paid_export_mode=True,
            source_uncertain=True,
        )
        during_status = session.status
        expired = await session.async_apply(
            _snapshot(
                timestamp=NOW + timedelta(seconds=100),
                ev_charging=None,
                ev_power_kw=None,
            ),
            _control(),
            _config(),
            no_paid_export_mode=True,
            source_uncertain=True,
        )
        return first, uncertain, during_status, expired, session.status

    first, uncertain, during, expired, end = asyncio.run(run())
    assert first.desired_min_soc_percent == 89.0
    assert uncertain.ev_grid_guard_status == "ev_battery_hold_source_grace"
    assert during["observed_ohme_hold_active"]
    assert during["latched_min_soc_percent"] == 89.0
    assert should_freeze_owned_ev_hold(
        owned_by_kems=True,
        latched_min_soc_percent=89.0,
        last_applied_action="self_use",
        observed_min_soc_on_grid_percent=89.0,
        last_verified_min_soc_on_grid_percent=89.0,
        cheap_period_confirmed=False,
        source_uncertainty_grace_active=True,
        no_paid_export_mode=True,
        ev_connected=True,
        operating_mode="control",
        master_control_enabled=True,
        user_commissioned=True,
        emergency_stop=False,
        island_mode_active=False,
        grid_available=True,
        pending_intelligent_ev_hold_active=True,
    )
    assert not should_freeze_owned_ev_hold(
        owned_by_kems=True,
        latched_min_soc_percent=89.0,
        last_applied_action="self_use",
        observed_min_soc_on_grid_percent=10.0,
        last_verified_min_soc_on_grid_percent=89.0,
        cheap_period_confirmed=False,
        source_uncertainty_grace_active=True,
        no_paid_export_mode=True,
        ev_connected=True,
        operating_mode="control",
        master_control_enabled=True,
        user_commissioned=True,
        emergency_stop=False,
        island_mode_active=False,
        grid_available=True,
        pending_intelligent_ev_hold_active=True,
    )
    assert expired.ev_grid_guard_status == "inactive"
    assert end["observed_ohme_hold_active"] is False


def test_wiring_does_not_promote_ohme_to_cheap_or_add_service_write():
    coordinator = (ROOT / "coordinator.py").read_text()
    hold = (ROOT / "ev_grid_hold_session.py").read_text()
    backend = (ROOT / "foxess_control_backend.py").read_text()
    tariff = (ROOT / "tariff.py").read_text()
    assert "measured_ohme_ev_charge_active(snapshot)" in coordinator
    assert "observed_ohme_hold_active" in coordinator
    assert "protect_measured_ohme_ev_hold(" in hold
    assert "pending_intelligent_ev_hold_active=hold_only_ev_active" in backend
    assert '"observed_ohme_hold_active": observed_ohme_hold_active' in backend
    assert "live_intelligent_slot is True" in tariff
    assert "services.async_call" not in hold
