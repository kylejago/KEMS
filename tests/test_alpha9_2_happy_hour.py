"""Alpha9.2 strict Happy Hour reward-hour and Ohme-control contracts."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from kems_core import ControlState, Snapshot

INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "kems"


def _install_package_stubs() -> None:
    custom_components = sys.modules.setdefault(
        "custom_components", types.ModuleType("custom_components")
    )
    custom_components.__path__ = [str(INTEGRATION_DIR.parent)]
    package = sys.modules.setdefault(
        "custom_components.kems", types.ModuleType("custom_components.kems")
    )
    package.__path__ = [str(INTEGRATION_DIR)]

    homeassistant = sys.modules.setdefault(
        "homeassistant", types.ModuleType("homeassistant")
    )
    helpers = sys.modules.setdefault(
        "homeassistant.helpers", types.ModuleType("homeassistant.helpers")
    )
    entity_registry = sys.modules.setdefault(
        "homeassistant.helpers.entity_registry",
        types.ModuleType("homeassistant.helpers.entity_registry"),
    )
    storage = sys.modules.setdefault(
        "homeassistant.helpers.storage",
        types.ModuleType("homeassistant.helpers.storage"),
    )
    storage.Store = object
    helpers.entity_registry = entity_registry
    helpers.storage = storage
    homeassistant.helpers = helpers


def _load_kems_module(name: str):
    full_name = f"custom_components.kems.{name}"
    spec = importlib.util.spec_from_file_location(
        full_name, INTEGRATION_DIR / f"{name}.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


_install_package_stubs()
_budget = _load_kems_module("happy_hour_budget")
_ohme = _load_kems_module("happy_hour_ohme_control")

allocate_reward_hour = _budget.allocate_reward_hour
apply_happy_hour_control = _budget.apply_happy_hour_control
reward_hour_ledger = _budget.reward_hour_ledger
reward_hour_windows = _budget.reward_hour_windows
ohme_happy_hour_write_decision = _ohme.ohme_happy_hour_write_decision

START = datetime(2026, 9, 5, 13, 0, tzinfo=UTC)


def _record(at: datetime, import_kw: float) -> SimpleNamespace:
    return SimpleNamespace(timestamp=at, grid_import_kw=import_kw)


def test_two_hour_happy_hour_is_two_independent_16kwh_buckets() -> None:
    end = START + timedelta(hours=2)
    windows = reward_hour_windows(START, end)
    assert windows == [
        (START, START + timedelta(hours=1)),
        (START + timedelta(hours=1), end),
    ]

    records = [
        _record(START - timedelta(minutes=1), 12.0),
        _record(START + timedelta(hours=1), 0.0),
    ]
    ledger = reward_hour_ledger(
        records,
        start=START,
        end=end,
        now=START + timedelta(hours=1),
    )
    assert ledger[0]["import_kwh"] == 12.0
    assert ledger[0]["remaining_kwh"] == 4.0
    assert ledger[1]["remaining_kwh"] == 16.0
    assert ledger[1]["cap_kwh"] == 16.0


def test_reward_hour_cap_does_not_borrow_from_second_hour() -> None:
    records = [
        _record(START - timedelta(minutes=1), 20.0),
        _record(START + timedelta(hours=1), 0.0),
    ]
    ledger = reward_hour_ledger(
        records,
        start=START,
        end=START + timedelta(hours=2),
        now=START + timedelta(hours=1),
    )
    assert ledger[0]["cap_reached"] is True
    assert ledger[0]["remaining_kwh"] == 0.0
    assert ledger[1]["remaining_kwh"] == 16.0


def test_battery_is_reserved_before_home_then_ev_gets_remainder() -> None:
    allocation = allocate_reward_hour(
        remaining_kwh=16.0,
        hours_remaining=1.0,
        home_grid_kw=1.0,
        battery_headroom_stored_kwh=20.0,
        charge_efficiency=1.0,
        max_charge_kw=7.0,
        inverter_limit_kw=7.0,
        site_import_limit_kw=None,
    )
    assert allocation["battery_reserved_input_kwh_remaining"] == 7.0
    assert allocation["projected_home_import_kwh_remaining"] == 1.0
    assert allocation["ev_allowance_kwh_remaining"] == 8.0
    assert allocation["battery_charge_target_kw"] == 7.0


def test_full_battery_releases_reward_allowance_to_home_and_ev() -> None:
    allocation = allocate_reward_hour(
        remaining_kwh=16.0,
        hours_remaining=1.0,
        home_grid_kw=1.0,
        battery_headroom_stored_kwh=0.0,
        charge_efficiency=0.95,
        max_charge_kw=7.0,
        inverter_limit_kw=7.0,
        site_import_limit_kw=None,
    )
    assert allocation["battery_reserved_input_kwh_remaining"] == 0.0
    assert allocation["ev_allowance_kwh_remaining"] == 15.0


def test_happy_hour_ev_overlay_is_separate_from_normal_cheap_authority() -> None:
    snapshot = Snapshot(
        timestamp=START,
        off_peak=False,
        intelligent_slot=False,
        ev_connected=True,
    )
    base = ControlState(
        desired_ev_charging_allowed=False,
        desired_battery_to_home_power_kw=2.0,
        desired_battery_export_power_kw=3.0,
        desired_total_discharge_power_kw=5.0,
    )
    active = apply_happy_hour_control(
        base,
        snapshot,
        {
            "happy_hour_import_authority_active": True,
            "ev_happy_hour_allowed": True,
            "charge_target_kw": 7.0,
        },
    )
    assert active.desired_ev_charging_allowed is True
    assert active.desired_charge_power_kw == 7.0
    assert active.desired_total_discharge_power_kw == 0.0
    assert active.desired_grid_export_allowed is False

    capped = apply_happy_hour_control(
        base,
        snapshot,
        {
            "happy_hour_import_authority_active": False,
            "current_reward_hour_cap_reached": True,
        },
    )
    assert capped == base


def test_ohme_write_requires_automatic_happy_hour_and_cap_margin() -> None:
    common = dict(
        enabled=True,
        authority_active=True,
        ledger_complete=True,
        ev_connected=True,
        data_fresh=True,
        plan_safe=True,
        grid_available=True,
        island_mode_active=False,
        power_down_active=False,
        emergency_stop=False,
        scan_interval_seconds=60,
        reward_remaining_kwh=8.0,
        ev_allowance_kwh=5.0,
        projected_home_grid_kw=1.0,
        battery_charge_target_kw=7.0,
    )
    allowed, _, _ = ohme_happy_hour_write_decision(automatic_source=True, **common)
    assert allowed is True
    manual, _, _ = ohme_happy_hour_write_decision(automatic_source=False, **common)
    assert manual is False
    near_cap, _, _ = ohme_happy_hour_write_decision(
        automatic_source=True,
        **{**common, "reward_remaining_kwh": 0.2},
    )
    assert near_cap is False


def test_ohme_write_path_is_narrow_and_foxess_remains_absent() -> None:
    source = (
        Path(__file__).parents[1] / "custom_components/kems/happy_hour_ohme_control.py"
    ).read_text(encoding="utf-8")
    assert source.count("self._hass.services.async_call(") == 1
    call_start = source.index("self._hass.services.async_call(")
    call_block = source[call_start : call_start + 300]
    assert '"select"' in call_block
    assert '"select_option"' in call_block
    assert 'happy_hour.get("source") == "octopus_energy"' in source
    assert "from .foxess" not in source
    assert "FoxESSCommand" not in source
