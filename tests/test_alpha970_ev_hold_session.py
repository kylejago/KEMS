"""Restart-safe EV hold does not lower its MinSOC floor during a charge."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from kems_core import ControlConfig, ControlState, Snapshot

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
NOW = datetime.now(UTC)


def _module():
    package = ModuleType("kems_hold_test")
    package.__path__ = [str(ROOT)]
    core_package = ModuleType("kems_hold_test.kems_core")
    core_package.__path__ = [str(ROOT / "kems_core")]
    fake_ha = ModuleType("homeassistant")
    fake_ha.__path__ = []
    fake_helpers = ModuleType("homeassistant.helpers")
    fake_helpers.__path__ = []
    fake_storage = ModuleType("homeassistant.helpers.storage")

    class FakeStore:
        data = {}

        def __init__(self, _hass, _version, key):
            self.key = key

        async def async_load(self):
            return self.data.get(self.key)

        async def async_save(self, value):
            self.data[self.key] = value

    fake_storage.Store = FakeStore
    fake_const = ModuleType("kems_hold_test.const")
    fake_const.DOMAIN = "kems"
    fake_const.STORAGE_NAMESPACE = "kems_test"
    import kems_core.ev_grid_guard as guard

    spec = importlib.util.spec_from_file_location(
        "kems_hold_test.ev_grid_hold_session", ROOT / "ev_grid_hold_session.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    modules = {
        "kems_hold_test": package,
        "kems_hold_test.const": fake_const,
        "kems_hold_test.kems_core": core_package,
        "kems_hold_test.kems_core.ev_grid_guard": guard,
        "homeassistant": fake_ha,
        "homeassistant.helpers": fake_helpers,
        "homeassistant.helpers.storage": fake_storage,
    }
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module, FakeStore


def _snap(*, soc=63.0, charging=True, power=6.0, **changes):
    d = dict(
        timestamp=NOW,
        off_peak=True,
        ev_connected=True,
        ev_charging=charging,
        ev_power_kw=power,
        ev_power_age_seconds=5.0,
        battery_soc=soc,
        house_load_kw=7.0 if charging else 1.0,
        grid_import_kw=6.0 if charging else 0.0,
        source_data_age_seconds=5.0,
        ev_load_in_house_load=True,
    )
    d.update(changes)
    return Snapshot(**d)


def _control():
    return ControlState(
        operating_mode="control",
        operating_reason="awaiting_export_tariff_charge",
        desired_work_mode="Self Use",
        desired_charge_power_kw=0.0,
        desired_min_soc_percent=60.0,
        grid_bypass_power_kw=7.0,
        desired_grid_export_allowed=False,
    )


def _config():
    return ControlConfig(
        operating_mode="control",
        site_import_limit_kw=14.5,
        normal_reserve_percent=15.0,
    )


def test_restart_preserves_max_floor_until_confirmed_charge_stop():
    module, store = _module()
    store.data.clear()

    async def exercise():
        first = module.EVGridHoldSession(object(), "ev-floor")
        await first.async_load()
        one = await first.async_apply(
            _snap(soc=63.0), _control(), _config(), no_paid_export_mode=True
        )
        two = await first.async_apply(
            _snap(soc=61.0), _control(), _config(), no_paid_export_mode=True
        )
        restarted = module.EVGridHoldSession(object(), "ev-floor")
        await restarted.async_load()
        three = await restarted.async_apply(
            _snap(soc=60.0), _control(), _config(), no_paid_export_mode=True
        )
        waiting = await restarted.async_apply(
            _snap(soc=60.0, charging=None, power=None),
            _control(),
            _config(),
            no_paid_export_mode=True,
        )
        stop = await restarted.async_apply(
            _snap(soc=60.0, charging=False, power=0.0),
            _control(),
            _config(),
            no_paid_export_mode=True,
        )
        return one, two, three, waiting, stop, restarted.status

    one, two, three, waiting, stop, status = asyncio.run(exercise())
    assert [x.desired_min_soc_percent for x in (one, two, three, waiting)] == [
        64.0, 64.0, 64.0, 64.0
    ]
    assert waiting.desired_charge_power_kw == 0.0
    assert status["latched_min_soc_percent"] is None
    assert stop.ev_grid_guard_status == "inactive"
    assert status["physical_isolation_proven"] is False


def test_stale_older_session_cannot_reapply_previous_night_floor():
    module, store = _module()
    store.data.clear()
    store.data["kems.ev-floor.kems_test.ev_grid_hold"] = {
        "held_floor": 99.0,
        "saved_at": (NOW - timedelta(hours=13)).isoformat(),
    }

    async def load():
        instance = module.EVGridHoldSession(object(), "ev-floor")
        await instance.async_load()
        return instance.status

    assert asyncio.run(load())["latched_min_soc_percent"] is None


def test_hold_session_never_issues_direct_foxess_or_ohme_service_writes():
    session = (ROOT / "ev_grid_hold_session.py").read_text(encoding="utf-8")
    assert "services.async_call" not in session
    assert "write_register" not in session
    assert "held_floor_percent=self._held_floor" in session
    coordinator = (ROOT / "coordinator.py").read_text(encoding="utf-8")
    assert "await self._ev_grid_hold.async_load()" in coordinator
    assert "await self._ev_grid_hold.async_apply(" in coordinator
    assert "await self._ev_grid_hold.async_save()" in coordinator
    diagnostics = (ROOT / "diagnostics.py").read_text(encoding="utf-8")
    assert '"ev_grid_hold_session": coordinator.ev_grid_hold_state' in diagnostics
