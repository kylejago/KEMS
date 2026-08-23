"""Regression coverage for selectable KEMS EV shadow policy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from kems_core import (
    EV_POLICY_DISABLED,
    EV_POLICY_SURPLUS,
    ControlConfig,
    ControlEngine,
    SimulationState,
    Snapshot,
)

NOW = datetime(2026, 8, 23, 14, 0, tzinfo=UTC)


def _snapshot(**changes) -> Snapshot:
    values = {
        "timestamp": NOW,
        "house_load_kw": 2.0,
        "grid_import_kw": 2.0,
        "off_peak": False,
        "intelligent_slot": False,
        "ev_connected": True,
        "ev_charging": False,
        "ev_power_kw": 0.0,
        "saving_session_active": False,
    }
    values.update(changes)
    return Snapshot(**values)


def _simulation(**changes) -> SimulationState:
    values = {
        "ready": True,
        "simulated_battery_soc": 80.0,
        "current_simulated_house_load_kw": 2.0,
        "current_simulated_solar_power_kw": 1.0,
        "current_simulated_battery_to_home_power_kw": 1.0,
        "target_battery_export_power_kw": 3.0,
        "saving_session_export_target_kw": 5.0,
    }
    values.update(changes)
    return SimulationState(**values)


def test_default_daytime_intelligent_slot_does_not_authorise_ev() -> None:
    state = ControlEngine().plan(
        _snapshot(intelligent_slot=True), _simulation(), NOW, ControlConfig()
    )
    assert state.desired_ev_charging_allowed is False


def test_default_negative_daytime_price_does_not_authorise_ev() -> None:
    state = ControlEngine().plan(
        _snapshot(current_import_rate=-4.5), _simulation(), NOW, ControlConfig()
    )
    assert state.desired_ev_charging_allowed is False


def test_default_overnight_allows_ev_and_isolates_battery() -> None:
    state = ControlEngine().plan(
        _snapshot(off_peak=True, ev_charging=True),
        _simulation(
            current_simulated_battery_to_home_power_kw=2.0,
            target_battery_export_power_kw=4.0,
        ),
        NOW,
        ControlConfig(),
    )
    assert state.desired_ev_charging_allowed is True
    assert state.desired_battery_to_home_power_kw == 0.0
    assert state.desired_battery_export_power_kw == 0.0
    assert state.desired_total_discharge_power_kw == 0.0
    assert state.desired_grid_export_allowed is False


def test_power_down_beats_overlapping_overnight_window() -> None:
    state = ControlEngine().plan(
        _snapshot(off_peak=True, saving_session_active=True),
        _simulation(),
        NOW,
        ControlConfig(),
    )
    assert state.desired_ev_charging_allowed is False
    assert state.operating_reason == "Power Down session active"


def test_surplus_mode_requires_real_connection_and_surplus_pv() -> None:
    engine = ControlEngine()
    engine._kems_ev_charging_policy = EV_POLICY_SURPLUS
    allowed = engine.plan(
        _snapshot(house_load_kw=1.5),
        _simulation(current_simulated_solar_power_kw=3.0),
        NOW,
        ControlConfig(),
    )
    blocked = engine.plan(
        _snapshot(house_load_kw=3.0),
        _simulation(current_simulated_solar_power_kw=1.0),
        NOW,
        ControlConfig(),
    )
    assert allowed.desired_ev_charging_allowed is True
    assert allowed.desired_total_discharge_power_kw == 0.0
    assert blocked.desired_ev_charging_allowed is False


def test_disabled_mode_always_blocks_ev() -> None:
    engine = ControlEngine()
    engine._kems_ev_charging_policy = EV_POLICY_DISABLED
    state = engine.plan(_snapshot(off_peak=True), _simulation(), NOW, ControlConfig())
    assert state.desired_ev_charging_allowed is False


def test_blocked_real_ev_load_is_not_fed_from_battery_outside_power_down() -> None:
    state = ControlEngine().plan(
        _snapshot(ev_charging=True, ev_power_kw=7.0, house_load_kw=8.0),
        _simulation(
            current_simulated_battery_to_home_power_kw=4.0,
            target_battery_export_power_kw=2.0,
        ),
        NOW,
        ControlConfig(),
    )
    assert state.desired_ev_charging_allowed is False
    assert state.desired_battery_to_home_power_kw == 0.0
    assert state.desired_battery_export_power_kw == 0.0
    assert state.desired_total_discharge_power_kw == 0.0


def test_emergency_stop_can_never_be_reopened_by_ev_policy() -> None:
    state = ControlEngine().plan(
        _snapshot(off_peak=True), _simulation(), NOW, ControlConfig(emergency_stop=True)
    )
    assert state.desired_ev_charging_allowed is False
    assert state.commands_permitted is False


def test_ev_policy_is_shadow_only_and_contains_no_hardware_calls() -> None:
    source = (
        Path(__file__).parents[1]
        / "custom_components/kems/kems_core/ev_charge_policy.py"
    )
    text = source.read_text(encoding="utf-8")
    assert ".services.async_call(" not in text
    assert "providers.ohme" not in text
    assert "providers.foxess" not in text
    assert "commands_permitted=True" not in text.replace(" ", "")
