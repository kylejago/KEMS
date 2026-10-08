"""Alpha9.75 verified EV-hold and source-grace regressions."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from kems_core import (
    ControlConfig,
    ControlState,
    Snapshot,
)
from kems_core.control_event_refresh import control_source_state_uncertain
from kems_core.control_write_authority import should_freeze_owned_ev_hold

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
COORDINATOR = KEMS / "coordinator.py"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"
NOW = datetime(2026, 9, 30, 19, 20, tzinfo=UTC)


def _freeze(**overrides: object) -> bool:
    values: dict[str, object] = {
        "owned_by_kems": True,
        "latched_min_soc_percent": 73.0,
        "last_applied_action": "self_use",
        "observed_min_soc_on_grid_percent": 73.0,
        "last_verified_min_soc_on_grid_percent": 73.0,
        "cheap_period_confirmed": True,
        "source_uncertainty_grace_active": False,
        "no_paid_export_mode": True,
        "ev_connected": True,
        "operating_mode": "control",
        "master_control_enabled": True,
        "user_commissioned": True,
        "emergency_stop": False,
        "island_mode_active": False,
        "grid_available": True,
    }
    values.update(overrides)
    return should_freeze_owned_ev_hold(**values)


def _session_module():
    package = ModuleType("kems_alpha975_hold_test")
    package.__path__ = [str(KEMS)]
    core_package = ModuleType("kems_alpha975_hold_test.kems_core")
    core_package.__path__ = [str(KEMS / "kems_core")]
    fake_ha = ModuleType("homeassistant")
    fake_ha.__path__ = []
    fake_helpers = ModuleType("homeassistant.helpers")
    fake_helpers.__path__ = []
    fake_storage = ModuleType("homeassistant.helpers.storage")

    class FakeStore:
        data: dict[str, dict[str, object]] = {}

        def __init__(self, _hass, _version, key):
            self.key = key

        async def async_load(self):
            return self.data.get(self.key)

        async def async_save(self, value):
            self.data[self.key] = value

    fake_storage.Store = FakeStore
    fake_const = ModuleType("kems_alpha975_hold_test.const")
    fake_const.DOMAIN = "kems"
    fake_const.STORAGE_NAMESPACE = "kems_test"
    import kems_core.ev_grid_guard as guard

    spec = importlib.util.spec_from_file_location(
        "kems_alpha975_hold_test.ev_grid_hold_session",
        KEMS / "ev_grid_hold_session.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    modules = {
        "kems_alpha975_hold_test": package,
        "kems_alpha975_hold_test.const": fake_const,
        "kems_alpha975_hold_test.kems_core": core_package,
        "kems_alpha975_hold_test.kems_core.ev_grid_guard": guard,
        "homeassistant": fake_ha,
        "homeassistant.helpers": fake_helpers,
        "homeassistant.helpers.storage": fake_storage,
    }
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module, FakeStore


def _snapshot(
    *,
    timestamp: datetime,
    cheap: bool,
    connected: bool | None,
    charging: bool | None,
    power: float | None,
) -> Snapshot:
    return Snapshot(
        timestamp=timestamp,
        off_peak=cheap,
        ev_connected=connected,
        ev_charging=charging,
        ev_power_kw=power,
        ev_power_age_seconds=5.0 if power is not None else None,
        battery_soc=72.0,
        house_load_kw=3.5,
        grid_import_kw=3.4,
        source_data_age_seconds=5.0,
        ev_load_in_house_load=True,
    )


def _control() -> ControlState:
    return ControlState(
        operating_mode="control",
        operating_reason="awaiting_export_tariff_charge",
        desired_work_mode="Self Use",
        desired_charge_power_kw=0.0,
        desired_min_soc_percent=60.0,
        grid_bypass_power_kw=7.0,
        desired_grid_export_allowed=False,
    )


def _config() -> ControlConfig:
    return ControlConfig(
        operating_mode="control",
        site_import_limit_kw=14.5,
        normal_reserve_percent=15.0,
    )


def test_alpha974_false_freeze_is_blocked_by_live_10_percent_readback() -> None:
    assert (
        _freeze(
            observed_min_soc_on_grid_percent=10.0,
            last_verified_min_soc_on_grid_percent=73.0,
        )
        is False
    )


def test_unavailable_readback_may_use_last_physical_verification() -> None:
    assert _freeze(observed_min_soc_on_grid_percent=None) is True
    assert (
        _freeze(
            observed_min_soc_on_grid_percent=None,
            last_verified_min_soc_on_grid_percent=10.0,
        )
        is False
    )


def test_source_grace_preserves_only_verified_hold() -> None:
    assert (
        _freeze(
            cheap_period_confirmed=False,
            source_uncertainty_grace_active=True,
            observed_min_soc_on_grid_percent=73.0,
        )
        is True
    )
    assert (
        _freeze(
            cheap_period_confirmed=False,
            source_uncertainty_grace_active=True,
            observed_min_soc_on_grid_percent=10.0,
        )
        is False
    )
    assert (
        _freeze(
            cheap_period_confirmed=False,
            source_uncertainty_grace_active=True,
            ev_connected=False,
        )
        is False
    )


def test_only_unknown_or_unavailable_sources_are_uncertain() -> None:
    assert control_source_state_uncertain(None) is True
    assert control_source_state_uncertain("unknown") is True
    assert control_source_state_uncertain("unavailable") is True
    assert control_source_state_uncertain("on") is False
    assert control_source_state_uncertain("off") is False
    assert control_source_state_uncertain("plugged_in") is False


def test_session_retains_floor_for_90_second_unavailable_grace_only() -> None:
    module, store = _session_module()
    store.data.clear()

    async def exercise():
        session = module.EVGridHoldSession(object(), "grace")
        await session.async_load()
        armed = await session.async_apply(
            _snapshot(
                timestamp=NOW,
                cheap=True,
                connected=True,
                charging=True,
                power=3.0,
            ),
            _control(),
            _config(),
            no_paid_export_mode=True,
        )
        grace = await session.async_apply(
            _snapshot(
                timestamp=NOW + timedelta(seconds=30),
                cheap=False,
                connected=None,
                charging=None,
                power=None,
            ),
            _control(),
            _config(),
            no_paid_export_mode=True,
            source_uncertain=True,
            source_grace_seconds=90,
        )
        grace_status = session.status
        expired = await session.async_apply(
            _snapshot(
                timestamp=NOW + timedelta(seconds=91),
                cheap=False,
                connected=None,
                charging=None,
                power=None,
            ),
            _control(),
            _config(),
            no_paid_export_mode=True,
            source_uncertain=True,
            source_grace_seconds=90,
        )
        return armed, grace, grace_status, expired, session.status

    armed, grace, grace_status, expired, expired_status = asyncio.run(exercise())
    assert armed.desired_min_soc_percent == 73.0
    assert grace.ev_grid_guard_status == "ev_battery_hold_source_grace"
    assert grace_status["latched_min_soc_percent"] == 73.0
    assert grace_status["source_uncertainty_grace_active"] is True
    assert expired.ev_grid_guard_status == "inactive"
    assert expired_status["latched_min_soc_percent"] is None
    assert expired_status["source_uncertainty_grace_active"] is False


def test_explicit_disconnect_or_usable_off_state_releases_without_grace() -> None:
    module, store = _session_module()
    store.data.clear()

    async def exercise(*, disconnected: bool, uncertain: bool):
        session = module.EVGridHoldSession(
            object(), f"release-{disconnected}-{uncertain}"
        )
        await session.async_load()
        await session.async_apply(
            _snapshot(
                timestamp=NOW,
                cheap=True,
                connected=True,
                charging=True,
                power=3.0,
            ),
            _control(),
            _config(),
            no_paid_export_mode=True,
        )
        result = await session.async_apply(
            _snapshot(
                timestamp=NOW + timedelta(seconds=30),
                cheap=False,
                connected=not disconnected,
                charging=False,
                power=0.0,
            ),
            _control(),
            _config(),
            no_paid_export_mode=True,
            source_uncertain=uncertain,
            source_grace_seconds=90,
        )
        return result, session.status

    disconnected_result, disconnected_status = asyncio.run(
        exercise(disconnected=True, uncertain=True)
    )
    explicit_off_result, explicit_off_status = asyncio.run(
        exercise(disconnected=False, uncertain=False)
    )
    assert disconnected_result.ev_grid_guard_status == "inactive"
    assert disconnected_status["latched_min_soc_percent"] is None
    assert explicit_off_result.ev_grid_guard_status == "inactive"
    assert explicit_off_status["latched_min_soc_percent"] is None


def test_backend_grace_and_freeze_paths_issue_no_new_writes() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    freeze = source.split("if frozen_ev_hold:", 1)[1].split(
        "elif not decision.commands_permitted:", 1
    )[0]
    assert "await self._async_number" not in freeze
    assert "await self._async_select" not in freeze
    assert "services.async_call" not in freeze
    assert '"hold_grace_unverified"' in source
    assert '"last_verified_min_soc_on_grid"' in source


def test_critical_transition_gets_bounded_two_second_follow_up_refresh() -> None:
    source = COORDINATOR.read_text(encoding="utf-8")
    assert "_ALPHA975_FOLLOW_UP_REFRESH_SECONDS = 2" in source
    assert "async_call_later(" in source
    assert "_follow_up_refresh" in source
    assert "_ALPHA975_EV_HOLD_SOURCE_GRACE_SECONDS = 90" in source


def test_alpha975_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.84"
    assert reason.startswith("Alpha9.84")
    assert "Alpha9.75" in reason
    assert "physically verified" in reason
    assert "90-second" in reason
    assert "2-second" in reason
    assert "does not create new cheap-period authority" in reason
    assert "explicit" in reason.lower()
    assert "Alpha9.74" in reason
