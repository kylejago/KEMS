"""Regression coverage for verified paused Ohme / house-only battery bridge."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _bridge_module():
    package = ModuleType("kems_bridge_186")
    package.__path__ = [str(KEMS)]
    const = ModuleType("kems_bridge_186.const")
    const.CONF_OHME_IDLE_HOUSE_BRIDGE_ENABLED = "ohme_idle_house_bridge_enabled"
    const.DOMAIN = "kems"
    const.STORAGE_NAMESPACE = "tests"
    ha = ModuleType("homeassistant")
    ha.__path__ = []
    helpers = ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    storage = ModuleType("homeassistant.helpers.storage")

    class Store:
        data = {}

        def __init__(self, _hass, _version, key):
            self.key = key

        async def async_load(self):
            return self.data.get(self.key)

        async def async_save(self, value):
            self.data[self.key] = dict(value)

    storage.Store = Store
    modules = {
        "kems_bridge_186": package,
        "kems_bridge_186.const": const,
        "homeassistant": ha,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.storage": storage,
    }
    spec = importlib.util.spec_from_file_location(
        "kems_bridge_186.ohme_idle_household_bridge",
        KEMS / "ohme_idle_household_bridge.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module, Store


class _States:
    def __init__(self, values):
        self.values = values

    def get(self, name):
        return self.values.get(name)


class _Services:
    def __init__(self, states, now):
        self.states = states
        self.now = now
        self.calls = []

    async def async_call(self, domain, service, payload, *, blocking):
        assert (domain, service, blocking) == ("select", "select_option", True)
        assert payload["entity_id"] == "select.ohme_epod_charge_mode"
        self.calls.append(payload["option"])
        mode = self.states.get("select.ohme_epod_charge_mode")
        mode.state = payload["option"]
        mode.last_reported = self.now


def _make_hass(now):
    values = {
        "select.ohme_epod_charge_mode": SimpleNamespace(
            state="Smart charge",
            attributes={"options": ["Smart charge", "Max charge", "Paused"]},
            last_reported=now,
        ),
        "sensor.ohme_epod_status": SimpleNamespace(
            state="plugged_in", attributes={}, last_reported=now
        ),
        "sensor.ohme_epod_power": SimpleNamespace(
            state="0", attributes={}, last_reported=now
        ),
        "number.foxess_min_soc": SimpleNamespace(
            state="15", attributes={}, last_reported=now
        ),
    }
    states = _States(values)
    services = _Services(states, now)
    return SimpleNamespace(states=states, services=services)


def _eligible(module, **overrides):
    kwargs = dict(
        opted_in=True,
        control_authorised=True,
        paid_agile_selected=True,
        cheap_period=False,
        active_session=False,
        ev_connected=True,
        ev_charging=False,
        ev_power_kw=0.0,
        ev_power_age_seconds=5.0,
        battery_soc=15.0,
        desired_export_kw=0.0,
        normal_reserve_percent=15.0,
    )
    kwargs.update(overrides)
    return module.household_bridge_eligible(**kwargs)


@pytest.mark.parametrize(
    "override",
    [
        {"opted_in": False},
        {"control_authorised": False},
        {"paid_agile_selected": False},
        {"cheap_period": True},
        {"active_session": True},
        {"ev_connected": None},
        {"ev_connected": False},
        {"ev_charging": True},
        {"ev_charging": None},
        {"ev_power_kw": 0.2},
        {"ev_power_kw": None},
        {"ev_power_age_seconds": 61.0},
        {"battery_soc": 10.0},
        {"battery_soc": 18.6},
        {"desired_export_kw": 0.5},
        {"normal_reserve_percent": 20.0},
    ],
)
def test_bridge_never_authorised_without_all_independent_gates(override):
    module, _ = _bridge_module()
    assert _eligible(module, **override) is False


def test_pause_is_requested_then_two_independent_reports_are_required():
    module, store = _bridge_module()
    store.data.clear()
    now = datetime.now(UTC)
    hass = _make_hass(now)
    bridge = module.OhmeIdleHouseholdBridge(
        hass,
        SimpleNamespace(
            entry_id="bridge-186",
            options={"ohme_idle_house_bridge_enabled": True},
        ),
    )

    async def exercise():
        await bridge.async_setup()
        kwargs = {
            "snapshot": None,
            "eligible": True,
            "ev_status_entity": "sensor.ohme_epod_status",
            "ev_power_entity": "sensor.ohme_epod_power",
        }
        request = await bridge.async_prepare(**kwargs, now=now)
        for name in (
            "select.ohme_epod_charge_mode",
            "sensor.ohme_epod_status",
            "sensor.ohme_epod_power",
        ):
            hass.states.get(name).last_reported = now + timedelta(seconds=1)
        first = await bridge.async_prepare(**kwargs, now=now + timedelta(seconds=1))
        # Repeating the same power report must not count twice.
        duplicate = await bridge.async_prepare(
            **kwargs, now=now + timedelta(seconds=30)
        )
        hass.states.get("select.ohme_epod_charge_mode").last_reported = now + timedelta(
            seconds=40
        )
        hass.states.get("sensor.ohme_epod_status").last_reported = now + timedelta(
            seconds=40
        )
        hass.states.get("sensor.ohme_epod_power").last_reported = now + timedelta(
            seconds=40
        )
        confirmed = await bridge.async_prepare(
            **kwargs, now=now + timedelta(seconds=40)
        )
        # No unpause while a physical 10% MinSOC remains.
        floor = hass.states.get("number.foxess_min_soc")
        floor.state = "10"
        floor.last_reported = now + timedelta(seconds=41)
        await bridge.async_restore_if_safe(
            keep_paused=False,
            min_soc_entity="number.foxess_min_soc",
            battery_soc=14.0,
            now=now + timedelta(seconds=41),
        )
        still_paused = hass.states.get("select.ohme_epod_charge_mode").state
        floor.state = "15"
        floor.last_reported = now + timedelta(seconds=42)
        await bridge.async_restore_if_safe(
            keep_paused=False,
            min_soc_entity="number.foxess_min_soc",
            battery_soc=15.0,
            now=now + timedelta(seconds=42),
        )
        return request, first, duplicate, confirmed, still_paused

    requested, first, duplicate, verified, paused = asyncio.run(exercise())
    assert (requested, first, duplicate, verified) == (False, False, False, True)
    assert paused == "Paused"
    assert hass.services.calls == ["Paused", "Smart charge"]
    assert bridge.status["owned"] is False
    assert bridge.status["enabled"] is True


def test_bridge_prearms_at_17_percent_but_never_without_independent_gates():
    module, _ = _bridge_module()
    assert _eligible(module, battery_soc=17.0) is True
    assert _eligible(module, battery_soc=18.5) is True
    assert _eligible(module, battery_soc=18.6) is False
    assert _eligible(module, battery_soc=17.0, opted_in=False) is False
    assert _eligible(module, battery_soc=17.0, ev_charging=True) is False


def test_owned_charger_pause_can_be_reverified_at_exactly_ten_percent():
    """Regression: 10% must NOT undo a KEMS-owned, physically paused Ohme."""
    module, store = _bridge_module()
    store.data.clear()
    assert _eligible(module, battery_soc=10.0) is False
    assert _eligible(module, battery_soc=10.0, owned_paused_at_floor=True) is True
    # Ownership is only an eligibility exception, not a bypass of EV,
    # tariff, export, physical-power, or absolute-reserve checks.
    for overrides in (
        {"ev_charging": True},
        {"ev_power_kw": 0.6},
        {"ev_connected": None},
        {"cheap_period": True},
        {"active_session": True},
        {"desired_export_kw": 1.0},
        {"control_authorised": False},
        {"opted_in": False},
        {"battery_soc": 9.9},
    ):
        checks = {"battery_soc": 10.0, "owned_paused_at_floor": True}
        checks.update(overrides)
        assert _eligible(module, **checks) is False

    now = datetime.now(UTC)
    hass = _make_hass(now)
    bridge = module.OhmeIdleHouseholdBridge(
        hass,
        SimpleNamespace(
            entry_id="floor-hold-193",
            options={"ohme_idle_house_bridge_enabled": True},
        ),
    )
    kwargs = {
        "snapshot": None,
        "eligible": True,
        "ev_status_entity": "sensor.ohme_epod_status",
        "ev_power_entity": "sensor.ohme_epod_power",
    }

    async def exercise():
        await bridge.async_setup()
        assert not await bridge.async_prepare(**kwargs, now=now)
        for name in (
            "select.ohme_epod_charge_mode",
            "sensor.ohme_epod_status",
            "sensor.ohme_epod_power",
        ):
            hass.states.get(name).last_reported = now + timedelta(seconds=1)
        assert not await bridge.async_prepare(**kwargs, now=now + timedelta(seconds=1))
        for name in (
            "select.ohme_epod_charge_mode",
            "sensor.ohme_epod_status",
            "sensor.ohme_epod_power",
        ):
            hass.states.get(name).last_reported = now + timedelta(seconds=41)
        assert await bridge.async_prepare(**kwargs, now=now + timedelta(seconds=41))
        assert bridge.owned is True
        # At 10%, the verified pause must remain; FoxESS may hold the
        # 10% physical floor rather than raising it to 15% on day rate.
        assert _eligible(module, battery_soc=10.0, owned_paused_at_floor=bridge.owned)
        assert await bridge.async_prepare(**kwargs, now=now + timedelta(seconds=45))
        floor = hass.states.get("number.foxess_min_soc")
        floor.state = "10"
        floor.last_reported = now + timedelta(seconds=45)
        await bridge.async_restore_if_safe(
            keep_paused=True,
            min_soc_entity="number.foxess_min_soc",
            battery_soc=10.0,
            now=now + timedelta(seconds=45),
        )
        assert hass.services.calls == ["Paused"]
        assert bridge.owned is True
        # At the cheap transition, raising/reading back the hardware floor
        # must precede any attempt to resume the EV.
        await bridge.async_restore_if_safe(
            keep_paused=False,
            min_soc_entity="number.foxess_min_soc",
            battery_soc=10.0,
            now=now + timedelta(seconds=46),
        )
        assert hass.services.calls == ["Paused"]
        floor.state = "15"
        floor.last_reported = now + timedelta(seconds=47)
        await bridge.async_restore_if_safe(
            keep_paused=False,
            min_soc_entity="number.foxess_min_soc",
            battery_soc=10.0,
            now=now + timedelta(seconds=47),
        )

    asyncio.run(exercise())
    assert hass.services.calls == ["Paused", "Smart charge"]
    assert bridge.owned is False


def test_physical_ev_power_must_still_be_zero_after_snapshot():
    module, store = _bridge_module()
    store.data.clear()
    now = datetime.now(UTC)
    hass = _make_hass(now)
    hass.states.get("sensor.ohme_epod_power").state = "1.5"
    bridge = module.OhmeIdleHouseholdBridge(
        hass,
        SimpleNamespace(
            entry_id="power-guard-192",
            options={"ohme_idle_house_bridge_enabled": True},
        ),
    )

    async def verify():
        await bridge.async_setup()
        return await bridge.async_prepare(
            snapshot=None,
            eligible=True,
            ev_status_entity="sensor.ohme_epod_status",
            ev_power_entity="sensor.ohme_epod_power",
            now=now,
        )

    assert asyncio.run(verify()) is False
    assert hass.services.calls == []
    assert bridge.status["pause_verified"] is False


def test_manually_paused_charger_cannot_establish_owned_bridge_proof():
    module, store = _bridge_module()
    store.data.clear()
    now = datetime.now(UTC)
    hass = _make_hass(now)
    hass.states.get("select.ohme_epod_charge_mode").state = "Paused"
    bridge = module.OhmeIdleHouseholdBridge(
        hass,
        SimpleNamespace(
            entry_id="manual-guard-192",
            options={"ohme_idle_house_bridge_enabled": True},
        ),
    )

    async def verify():
        await bridge.async_setup()
        return await bridge.async_prepare(
            snapshot=None,
            eligible=True,
            ev_status_entity="sensor.ohme_epod_status",
            ev_power_entity="sensor.ohme_epod_power",
            now=now,
        )

    assert asyncio.run(verify()) is False
    assert bridge.status["owned"] is False
    assert hass.services.calls == []


def test_restart_does_not_reuse_pause_proof():
    module, store = _bridge_module()
    store.data.clear()
    now = datetime.now(UTC)
    hass = _make_hass(now)
    entry = SimpleNamespace(
        entry_id="restart-186", options={"ohme_idle_house_bridge_enabled": True}
    )

    async def exercise():
        original = module.OhmeIdleHouseholdBridge(hass, entry)
        await original.async_setup()
        await original.async_prepare(
            snapshot=None,
            eligible=True,
            ev_status_entity="sensor.ohme_epod_status",
            ev_power_entity="sensor.ohme_epod_power",
            now=now,
        )
        later = module.OhmeIdleHouseholdBridge(hass, entry)
        await later.async_setup()
        return (
            await later.async_prepare(
                snapshot=None,
                eligible=True,
                ev_status_entity="sensor.ohme_epod_status",
                ev_power_entity="sensor.ohme_epod_power",
                now=now + timedelta(seconds=2),
            ),
            later.status,
        )

    first, state = asyncio.run(exercise())
    assert first is False
    assert state["owned"] is True
    assert state["pause_verified"] is False


def test_opt_in_and_foxess_15pct_export_limits_remain_distinct():
    const = (KEMS / "const.py").read_text(encoding="utf-8")
    backend = (KEMS / "foxess_control_backend.py").read_text(encoding="utf-8")
    authority = (KEMS / "kems_core" / "control_write_authority.py").read_text(
        encoding="utf-8"
    )
    assert "CONF_OHME_IDLE_HOUSE_BRIDGE_ENABLED: False" in const
    assert '"ohme_idle_household_bridge": self._ohme_idle_bridge.status' in backend
    assert "if bridge_paused_verified:" in backend
    assert "paid_idle_household_10_percent_authorised" in backend
    assert "and ev_confirmed_unplugged" in backend
    assert "return 10.0" in authority
    assert "_PAID_EXPORT_STAGE_KW = 1.0" in backend
    assert "_PAID_EXPORT_PROOF_SAMPLES = 2" in backend


def test_release_metadata_pin():
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    assert manifest["version"] == "0.9.0-alpha9.200"
    assert bundle["maintenance"]["reason"].startswith("Alpha9.200:")
