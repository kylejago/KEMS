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
    assert passed == total == 15


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
    # Solar is already producing 3kW, so the battery can contribute only
    # 4kW under the shared KH7 7kW AC cap: 2kW home + 2kW export.
    assert state.desired_total_discharge_power_kw == 4.0
    assert state.desired_battery_export_power_kw == 2.0
    assert state.total_kh7_ac_output_kw == 7.0
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
    # Grid-connected high load uses bypass and must not be labelled as EPS load.
    assert state.whole_house_eps_load_kw == 0.0
    assert state.eps_status == "not_active"
    assert state.eps_warning is False
    assert state.eps_critical is False
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


def test_cheap_charge_allows_grid_bypass_above_kh7_output_limit() -> None:
    state = ControlEngine().plan(
        _snapshot(off_peak=True, house_load_kw=2.0, grid_import_kw=2.0),
        _simulation(current_simulated_house_load_kw=2.0),
        NOW,
        ControlConfig(),
    )
    assert state.desired_charge_power_kw == 7.0
    assert state.grid_bypass_power_kw == 2.0
    assert state.total_site_import_kw == 9.0
    assert state.plan_safe is True


def test_site_import_limit_reduces_flexible_battery_charge() -> None:
    state = ControlEngine().plan(
        _snapshot(off_peak=True, house_load_kw=2.0, grid_import_kw=2.0),
        _simulation(current_simulated_house_load_kw=2.0),
        NOW,
        ControlConfig(site_import_limit_kw=8.0),
    )
    assert state.desired_charge_power_kw == 6.0
    assert state.total_site_import_kw == 8.0
    assert state.site_import_headroom_kw == 0.0
    assert state.site_import_limit_exceeded is False


def test_island_solar_and_battery_share_eps_output_cap() -> None:
    state = ControlEngine().plan(
        _snapshot(),
        _simulation(
            current_simulated_house_load_kw=8.0,
            current_simulated_solar_power_kw=4.0,
            simulated_battery_soc=80.0,
        ),
        NOW,
        ControlConfig(virtual_scenario="grid_outage_high_load"),
    )
    assert state.solar_to_house_kw + state.battery_to_house_kw <= 7.0
    assert state.eps_status == "unsafe"
    assert state.eps_load_reduction_required_kw > 0.0


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


def test_awaiting_export_tariff_control_forces_self_use_and_zero_export() -> None:
    """Shadow/live planner must never request grid export before tariff activation."""
    state = ControlEngine().plan(
        _snapshot(house_load_kw=2.0),
        _simulation(
            no_export_mode_active=True,
            export_tariff_active=False,
            current_simulated_solar_power_kw=1.0,
            current_simulated_battery_to_home_power_kw=1.0,
            current_simulated_grid_import_kw=0.0,
            current_simulated_grid_export_kw=0.0,
            target_battery_export_power_kw=0.0,
        ),
        NOW,
        ControlConfig(),
    )
    assert state.operating_reason == "awaiting_export_tariff"
    assert state.desired_work_mode == "Self Use"
    assert state.desired_battery_export_power_kw == 0.0
    assert state.desired_grid_export_allowed is False
    assert state.total_site_import_kw == 0.0


def test_awaiting_export_tariff_cheap_control_honours_smart_charge_request() -> None:
    """Control should use the simulation's reduced overnight grid-charge target."""
    state = ControlEngine().plan(
        _snapshot(off_peak=True, house_load_kw=1.0),
        _simulation(
            no_export_mode_active=True,
            export_tariff_active=False,
            current_simulated_battery_charge_power_kw=2.5,
            current_simulated_total_site_import_kw=3.5,
        ),
        NOW,
        ControlConfig(),
    )
    assert state.operating_reason == "awaiting_export_tariff_charge"
    assert state.desired_charge_power_kw == 2.5
    assert state.desired_grid_export_allowed is False


def test_awaiting_export_tariff_cheap_control_uses_solar_for_house_headroom() -> None:
    """Solar-serving house load should leave more site headroom for cheap charging."""
    state = ControlEngine().plan(
        _snapshot(off_peak=True, house_load_kw=3.0),
        _simulation(
            no_export_mode_active=True,
            export_tariff_active=False,
            current_simulated_house_load_kw=3.0,
            current_simulated_solar_power_kw=2.0,
            current_simulated_battery_charge_power_kw=4.0,
            current_simulated_grid_bypass_power_kw=None,
        ),
        NOW,
        ControlConfig(site_import_limit_kw=5.0),
    )
    assert state.grid_bypass_power_kw == 1.0
    assert state.desired_charge_power_kw == 4.0
    assert state.total_site_import_kw == 5.0
    assert state.site_import_limit_exceeded is False
