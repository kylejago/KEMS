"""Safety regression tests for the pre-installation control lab."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kems_core import (
    ControlConfig,
    ControlEngine,
    SimulationState,
    Snapshot,
    run_preflight_suite,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _snapshot(**changes) -> Snapshot:
    values = {
        "timestamp": NOW,
        "house_load_kw": 2.0,
        "grid_import_kw": 2.0,
        "saving_session_active": False,
        "off_peak": False,
        "intelligent_slot": False,
        "ev_charging": False,
    }
    values.update(changes)
    return Snapshot(**values)


def _simulation(**changes) -> SimulationState:
    values = {
        "ready": True,
        "simulated_battery_soc": 70.0,
        "current_simulated_house_load_kw": 2.0,
        "current_simulated_solar_power_kw": 3.0,
        "current_simulated_battery_to_home_power_kw": 2.0,
        "target_battery_export_power_kw": 1.5,
        "saving_session_export_target_kw": 5.0,
    }
    values.update(changes)
    return SimulationState(**values)


def test_preflight_suite_passes_default_kh7_safety_constraints() -> None:
    passed, total = run_preflight_suite(ControlConfig())
    assert passed == total == 12


def test_normal_paced_export_plan_respects_seven_kw_limit() -> None:
    state = ControlEngine().plan(_snapshot(), _simulation(), NOW, ControlConfig())
    assert state.operating_reason == "paced_export"
    assert state.desired_battery_to_home_power_kw == 2.0
    assert state.desired_battery_export_power_kw == 1.5
    assert state.desired_total_discharge_power_kw == 3.5
    assert state.plan_safe is True
    assert state.commands_permitted is False


def test_confirmed_cheap_period_requests_charge_and_no_export() -> None:
    state = ControlEngine().plan(
        _snapshot(off_peak=True),
        _simulation(),
        NOW,
        ControlConfig(),
    )
    assert state.operating_reason == "confirmed_cheap_charge"
    assert state.desired_charge_power_kw == 7.0
    assert state.desired_battery_export_power_kw == 0.0
    assert state.desired_grid_export_allowed is False


def test_power_down_uses_session_export_target() -> None:
    state = ControlEngine().plan(
        _snapshot(saving_session_active=True),
        _simulation(),
        NOW,
        ControlConfig(),
    )
    assert state.operating_reason == "power_down_session"
    assert state.desired_total_discharge_power_kw == 7.0
    assert state.desired_battery_export_power_kw == 5.0
    assert state.desired_ev_charging_allowed is False


def test_daylight_island_uses_solar_then_charges_battery() -> None:
    state = ControlEngine().plan(
        _snapshot(),
        _simulation(
            current_simulated_house_load_kw=2.0,
            current_simulated_solar_power_kw=5.0,
        ),
        NOW,
        ControlConfig(virtual_scenario="grid_outage_daylight"),
    )
    assert state.island_mode_active is True
    assert state.solar_to_house_kw == 2.0
    assert state.solar_to_battery_kw == 3.0
    assert state.virtual_scenario_solar_power_kw == 5.0
    assert state.virtual_scenario_house_load_kw == 2.0
    assert state.battery_to_house_kw == 0.0
    assert state.desired_battery_export_power_kw == 0.0
    assert state.desired_ev_charging_allowed is False


def test_night_island_uses_battery_to_emergency_floor() -> None:
    state = ControlEngine().plan(
        _snapshot(),
        _simulation(
            current_simulated_house_load_kw=2.4,
            simulated_battery_soc=14.0,
        ),
        NOW,
        ControlConfig(virtual_scenario="grid_outage_night"),
    )
    assert state.solar_to_house_kw == 0.0
    assert state.battery_to_house_kw == 2.4
    assert state.desired_min_soc_percent == 10.0
    assert state.island_conservation_threshold_percent == 20.0
    assert state.island_emergency_floor_percent == 10.0
    assert state.island_battery_status == "conservation"
    assert state.estimated_outage_runtime_hours == 0.89
    assert state.desired_grid_export_allowed is False


def test_high_whole_house_load_triggers_eps_critical_warning() -> None:
    state = ControlEngine().plan(
        _snapshot(),
        _simulation(),
        NOW,
        ControlConfig(virtual_scenario="high_house_load"),
    )
    assert state.whole_house_eps_load_kw == 6.44
    # Grid-connected high load is measured but is not island load, so no island alarm.
    assert state.island_mode_active is False


def test_island_overload_is_marked_critical_and_unsafe() -> None:
    state = ControlEngine().plan(
        _snapshot(),
        _simulation(),
        NOW,
        ControlConfig(virtual_scenario="grid_outage_high_load"),
    )
    assert state.island_mode_active is True
    assert state.eps_critical is True
    assert state.plan_safe is False
    assert "exceeds" in state.blocked_reason.lower()


def test_grid_flapping_holds_resilience_mode() -> None:
    state = ControlEngine().plan(
        _snapshot(),
        _simulation(),
        NOW,
        ControlConfig(virtual_scenario="grid_flapping"),
    )
    assert state.operating_reason == "grid_restoration_hold"
    assert state.desired_grid_export_allowed is False
    assert state.desired_ev_charging_allowed is False


def test_emergency_stop_overrides_every_other_priority() -> None:
    state = ControlEngine().plan(
        _snapshot(saving_session_active=True, off_peak=True),
        _simulation(),
        NOW,
        ControlConfig(emergency_stop=True),
    )
    assert state.operating_reason == "emergency_stop"
    assert state.desired_charge_power_kw == 0.0
    assert state.desired_total_discharge_power_kw == 0.0


def test_stale_data_blocks_plan() -> None:
    state = ControlEngine().plan(
        _snapshot(timestamp=NOW - timedelta(minutes=10)),
        _simulation(),
        NOW,
        ControlConfig(stale_data_seconds=180),
    )
    assert state.operating_reason == "stale_data_failsafe"
    assert state.data_fresh is False
    assert state.plan_safe is False


def test_live_control_stays_hard_blocked_before_real_backend() -> None:
    state = ControlEngine().plan(
        _snapshot(),
        _simulation(),
        NOW,
        ControlConfig(
            operating_mode="control",
            commissioned=True,
            control_enabled=True,
        ),
    )
    assert state.commands_permitted is False
    assert state.real_backend_available is False
    assert "backend" in state.blocked_reason.lower()


def test_island_stops_battery_at_emergency_floor() -> None:
    state = ControlEngine().plan(
        _snapshot(),
        _simulation(
            current_simulated_house_load_kw=2.4,
            simulated_battery_soc=10.0,
        ),
        NOW,
        ControlConfig(virtual_scenario="grid_outage_night"),
    )
    assert state.battery_to_house_kw == 0.0
    assert state.estimated_outage_runtime_hours == 0.0
    assert state.island_battery_status == "emergency_floor"
    assert "emergency floor" in state.next_action.lower()
