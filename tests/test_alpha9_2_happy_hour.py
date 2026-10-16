"""Alpha9.2 strict Happy Hour reward-hour and Ohme-control contracts."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from kems_core import ControlState, Snapshot
from kems_core.control_write_authority import assess_foxess_control_write_authority

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


def test_hard_cap_clips_battery_request_for_non_curtailable_home_before_ev() -> None:
    allocation = allocate_reward_hour(
        remaining_kwh=8.0,
        hours_remaining=1.0,
        home_grid_kw=4.0,
        battery_headroom_stored_kwh=20.0,
        charge_efficiency=1.0,
        max_charge_kw=7.0,
        inverter_limit_kw=7.0,
        site_import_limit_kw=None,
    )
    assert allocation["battery_reserved_input_kwh_remaining"] == 4.0
    assert allocation["projected_home_import_kwh_remaining"] == 4.0
    assert allocation["ev_allowance_kwh_remaining"] == 0.0
    assert (
        allocation["battery_reserved_input_kwh_remaining"]
        + allocation["projected_home_import_kwh_remaining"]
        + allocation["ev_allowance_kwh_remaining"]
        <= 8.0
    )


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


def test_happy_hour_overlay_cannot_unlock_alpha969_shadow_route() -> None:
    """An overwritten reason cannot promote new cheap routing to live KH7."""
    snapshot = Snapshot(
        timestamp=START,
        off_peak=True,
        ev_connected=True,
    )
    proposal = ControlState(
        operating_mode="control",
        operating_reason="no_export_extra_slot",
        alpha969_routing_shadow_only=True,
        desired_work_mode="Force Charge",
        desired_charge_power_kw=2.0,
        desired_min_soc_percent=60.0,
        desired_grid_export_allowed=False,
        desired_battery_export_power_kw=0.0,
        grid_available=True,
        data_fresh=True,
        plan_safe=True,
        preflight_passed=15,
        preflight_total=15,
    )
    overlaid = apply_happy_hour_control(
        proposal,
        snapshot,
        {
            "happy_hour_import_authority_active": True,
            "ev_happy_hour_allowed": True,
            "charge_target_kw": 7.0,
        },
    )
    assert overlaid.operating_reason == "happy_hour_reward_hour"
    assert overlaid.alpha969_routing_shadow_only is True
    decision = assess_foxess_control_write_authority(
        overlaid,
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=True,
        cheap_period_confirmed=True,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
    )
    assert decision.commands_permitted is False
    assert decision.action == "release"
    assert "shadow-only pending physical" in decision.reason


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


def test_alpha9111_confirmed_ohme_charge_mode_is_discovered_when_plugged_in() -> None:
    state = SimpleNamespace(
        state="Smart charge",
        attributes={"options": ["Smart charge", "Max charge", "Paused"]},
    )
    controller = _ohme.OhmeHappyHourController.__new__(_ohme.OhmeHappyHourController)
    controller._ev_status_entity = "sensor.ohme_epod_status"
    controller._hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda entity: (
                state if entity == "select.ohme_epod_charge_mode" else None
            )
        )
    )
    assert controller._charge_mode_entity() == "select.ohme_epod_charge_mode"


def test_alpha9111_ohme_mode_unavailable_does_not_allow_a_blind_write(
    monkeypatch,
) -> None:
    controller = _ohme.OhmeHappyHourController.__new__(_ohme.OhmeHappyHourController)
    controller._ev_status_entity = "sensor.ohme_epod_status"
    controller._hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda entity: SimpleNamespace(
                state="unavailable",
                attributes={"options": ["Smart charge", "Max charge", "Paused"]},
            )
        )
    )
    monkeypatch.setattr(
        _ohme.er,
        "async_get",
        lambda hass: SimpleNamespace(entities={}, async_get=lambda entity: None),
        raising=False,
    )
    assert controller._charge_mode_entity() is None


def test_alpha9111_kems_confirmed_booking_enables_ohme_but_not_manual() -> None:
    eligible = {
        "source": "octopus_energy",
        "automatic_status": "detected_kems_booking",
        "booking_authoritative": True,
        "booking_source": "kems_auto_join",
    }
    assert _ohme._automatic_happy_hour_source(eligible) is True
    assert (
        _ohme._automatic_happy_hour_source({**eligible, "booking_authoritative": False})
        is False
    )
    assert _ohme._automatic_happy_hour_source({**eligible, "source": "manual"}) is False
    assert (
        _ohme._automatic_happy_hour_source(
            {**eligible, "automatic_status": "detected_upcoming"}
        )
        is False
    )
    assert (
        _ohme._automatic_happy_hour_source(
            {"source": "octopus_energy", "automatic_status": "detected_active"}
        )
        is True
    )


def test_alpha9111_restores_prior_paused_mode_after_owned_max_charge() -> None:
    current = SimpleNamespace(
        state="Max charge",
        attributes={"options": ["Smart charge", "Max charge", "Paused"]},
    )
    calls = []

    async def call(domain, action, data, **kwargs):
        calls.append((domain, action, dict(data)))
        current.state = data["option"]

    controller = _ohme.OhmeHappyHourController.__new__(_ohme.OhmeHappyHourController)
    controller._hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda entity: current),
        services=SimpleNamespace(async_call=call),
    )
    controller._owned = True
    controller._previous_mode = "Paused"
    controller._restore_attempts = 0
    controller._last_result = ""
    controller._last_command = None
    controller._last_command_at = None

    async def save():
        return None

    controller._async_save = save
    asyncio.run(controller._async_restore("select.ohme_epod_charge_mode"))
    assert calls == [
        (
            "select",
            "select_option",
            {"entity_id": "select.ohme_epod_charge_mode", "option": "Paused"},
        )
    ]
    assert controller._owned is False
    assert current.state == "Paused"


def test_alpha9111_physical_headroom_uses_soc_upper_bound_not_export_lower_bound(
    monkeypatch,
) -> None:
    now = datetime(2026, 10, 18, 11, 0, tzinfo=UTC)
    snapshot = SimpleNamespace(
        battery_soc=95.0,
        source_age_seconds={"battery_soc": 60.0},
    )
    manager = SimpleNamespace(
        _kems_physical_planning_context={
            "snapshot": snapshot,
            "control": SimpleNamespace(max_charge_kw=9.0),
        }
    )
    fake = types.ModuleType("custom_components.kems.agile_physical_planning")
    fake.physical_planning_soc = lambda manager, now, config: (
        80.0,
        {"available": True},
    )
    monkeypatch.setitem(
        sys.modules, "custom_components.kems.agile_physical_planning", fake
    )
    evidence = _budget.verified_happy_hour_physical_headroom(
        manager,
        now=now,
        config=SimpleNamespace(battery_capacity_kwh=50.0),
    )
    assert evidence["physical_soc_verified"] is True
    assert evidence["current_physical_soc_percent"] == 95.0
    assert evidence["physical_soc_lower_bound_percent"] == 80.0
    # 5% physical space is only 2.5 kWh, less 9 kW x 60 s and 0.5 kWh.
    assert evidence["physical_battery_headroom_kwh"] == 1.85
    assert _budget._adjusted_headroom({}, evidence, None) == 1.85


def test_alpha9111_no_verified_physical_soc_never_uses_simulated_headroom(
    monkeypatch,
) -> None:
    fake = types.ModuleType("custom_components.kems.agile_physical_planning")
    fake.physical_planning_soc = lambda manager, now, config: (
        None,
        {"available": False, "reason": "stale FoxESS source"},
    )
    monkeypatch.setitem(
        sys.modules, "custom_components.kems.agile_physical_planning", fake
    )
    manager = SimpleNamespace(_kems_physical_planning_context=None)
    physical = _budget.verified_happy_hour_physical_headroom(
        manager,
        now=START,
        config=SimpleNamespace(battery_capacity_kwh=56.42),
    )
    assert physical["physical_soc_verified"] is False
    assert physical["current_physical_soc_percent"] is None
    assert (
        _budget._adjusted_headroom(
            {"happy_hour_adjusted_soc_percent": 6.07},
            {
                "current_simulated_soc_percent": 6.07,
                "current_battery_headroom_kwh": 50.0,
                **physical,
            },
            SimpleNamespace(battery_capacity_kwh=56.42),
        )
        == 0.0
    )


def test_alpha9111_ohme_restoration_waits_when_mode_becomes_unavailable() -> None:
    current = SimpleNamespace(
        state="unavailable",
        attributes={"options": ["Smart charge", "Max charge", "Paused"]},
    )
    calls = []

    async def call(domain, action, data, **kwargs):
        calls.append(dict(data))

    controller = _ohme.OhmeHappyHourController.__new__(_ohme.OhmeHappyHourController)
    controller._hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda entity: current),
        services=SimpleNamespace(async_call=call),
    )
    controller._owned = True
    controller._previous_mode = "Paused"
    controller._restore_attempts = 0
    controller._last_result = ""
    controller._last_command = None
    controller._last_command_at = None

    async def save():
        raise AssertionError("Do not release ownership without a valid mode")

    controller._async_save = save
    asyncio.run(controller._async_restore("select.ohme_epod_charge_mode"))
    assert controller._owned is True
    assert controller._restore_attempts == 0
    assert "deferred" in controller._last_result
    assert calls == []
