"""Regression coverage for the canonical overnight-only EV policy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from kems_core import ControlConfig, ControlEngine, SimulationState, Snapshot

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


def test_daytime_intelligent_slot_does_not_authorise_ev_charging() -> None:
    state = ControlEngine().plan(
        _snapshot(intelligent_slot=True, ev_charging=True),
        _simulation(),
        NOW,
        ControlConfig(),
    )

    assert state.desired_ev_charging_allowed is False
    assert state.desired_battery_export_power_kw > 0.0


def test_negative_daytime_price_does_not_authorise_ev_charging() -> None:
    state = ControlEngine().plan(
        _snapshot(current_import_rate=-4.5),
        _simulation(),
        NOW,
        ControlConfig(),
    )

    assert state.desired_ev_charging_allowed is False


def test_overnight_window_allows_ev_and_blocks_battery_discharge_export() -> None:
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


def test_power_down_still_blocks_ev_if_it_overlaps_overnight() -> None:
    state = ControlEngine().plan(
        _snapshot(off_peak=True, saving_session_active=True),
        _simulation(),
        NOW,
        ControlConfig(),
    )

    assert state.desired_ev_charging_allowed is False


def test_emergency_stop_can_never_be_reopened_by_ev_policy() -> None:
    state = ControlEngine().plan(
        _snapshot(off_peak=True),
        _simulation(),
        NOW,
        ControlConfig(emergency_stop=True),
    )

    assert state.desired_ev_charging_allowed is False
    assert state.commands_permitted is False


def test_ev_policy_is_shadow_only_and_contains_no_hardware_calls() -> None:
    source = Path(__file__).parents[1] / "custom_components/kems/kems_core/ev_charge_policy.py"
    text = source.read_text(encoding="utf-8")

    assert ".services.async_call(" not in text
    assert "ohme" not in text.lower()
    assert "foxess" not in text.lower()
    assert "commands_permitted=True" not in text.replace(" ", "")
