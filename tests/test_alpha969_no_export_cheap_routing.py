"""Alpha9.69 proposed No paid export cheap routing — no hardware proof claims."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from kems_core import (
    ControlConfig,
    ControlEngine,
    SimulationConfig,
    SimulationState,
    Snapshot,
)
from kems_core.no_export_cheap import (
    infer_ev_load_in_house_load,
    no_export_cheap_period_kind,
    route_no_export_cheap,
    split_no_export_demand,
)

UK = ZoneInfo("Europe/London")
OVERNIGHT = datetime(2026, 9, 26, 23, 45, tzinfo=UK)
EXTRA = datetime(2026, 9, 26, 14, 0, tzinfo=UK)


def _snapshot(*, when=OVERNIGHT, soc=80.0, house=1.0, **changes):
    values = dict(
        timestamp=when,
        off_peak=True,
        house_load_kw=house,
        solar_power_kw=0.0,
        battery_soc=soc,
        grid_import_kw=house,
        grid_export_kw=0.0,
        next_offpeak_start=when + timedelta(hours=24),
        offpeak_end=when + timedelta(hours=5),
    )
    values.update(changes)
    return Snapshot(**values)


def _route(snapshot, *, stored=8.0, target=6.0, solar=0.0, capacity=10.0):
    return route_no_export_cheap(
        snapshot,
        load_kw=snapshot.house_load_kw,
        solar_kw=solar,
        battery_kwh=stored,
        target_stored_kwh=target,
        config=SimulationConfig(
            battery_capacity_kwh=capacity,
            battery_reserve_percent=10,
            max_charge_kw=7,
            max_discharge_kw=7,
            inverter_limit_kw=7,
            charge_efficiency=1,
            discharge_efficiency=1,
            export_tariff_status="inactive",
            site_import_limit_kw=14.5,
        ),
        hours=1,
    )


def _config(*, mode="shadow"):
    return ControlConfig(
        operating_mode=mode,
        control_enabled=True,
        commissioned=True,
        normal_reserve_percent=10,
        battery_capacity_kwh=10,
        max_charge_kw=7,
        max_discharge_kw=7,
        inverter_limit_kw=7,
        site_import_limit_kw=14.5,
    )


def _simulation(*, target=60.0, **changes):
    values = dict(
        no_export_mode_active=True,
        overnight_charge_target_percent=target,
        home_reserve_forecast_source="recent_average",
        forecast_home_until_next_cheap_kwh=5.0,
        simulated_battery_soc=80,
        current_simulated_house_load_kw=1,
        current_simulated_solar_power_kw=0,
        current_simulated_battery_to_home_power_kw=1,
    )
    values.update(changes)
    return SimulationState(**values)


def test_cheap_window_classification_requires_confirmed_tariff():
    assert no_export_cheap_period_kind(_snapshot()) == "overnight"
    assert no_export_cheap_period_kind(_snapshot(when=EXTRA)) == "extra_intelligent"
    assert no_export_cheap_period_kind(_snapshot(off_peak=False)) is None
    assert (
        no_export_cheap_period_kind(
            _snapshot(
                when=EXTRA,
                off_peak=False,
                intelligent_slot=True,
                ev_charging=True,
                intelligent_slot_evidence={"large_import_permitted": True},
            )
        )
        == "extra_intelligent"
    )


def test_80_to_70_stays_70_without_export_or_forced_discharge():
    route = _route(_snapshot(house=1), stored=8, target=6)
    assert route.battery_to_home_kwh == pytest.approx(1)
    assert route.battery_stored_kwh == pytest.approx(7)
    assert route.grid_import_kwh == 0
    assert route.solar_curtailed_kwh == 0
    route = _route(_snapshot(house=0), stored=7, target=6)
    assert route.battery_to_home_kwh == 0
    assert route.battery_stored_kwh == 7
    assert route.grid_import_kwh == 0


def test_at_floor_holds_and_below_floor_charges_only_shortfall():
    at = _route(_snapshot(), stored=6, target=6)
    assert at.battery_to_home_kwh == 0
    assert at.grid_import_kwh == pytest.approx(1)
    below = _route(_snapshot(), stored=5.5, target=6)
    assert below.battery_to_home_kwh == 0
    assert below.grid_to_battery_input_kwh == pytest.approx(0.5)
    assert below.battery_stored_kwh == pytest.approx(6)
    assert below.grid_import_kwh == pytest.approx(1.5)


@pytest.mark.parametrize("included,load", [(True, 8.0), (False, 2.0)])
def test_ev_grid_and_house_battery_are_disjoint_when_scope_proven(included, load):
    snap = _snapshot(
        house=load,
        ev_charging=True,
        ev_power_kw=6.0,
        ev_load_in_house_load=included,
    )
    split = split_no_export_demand(snap, load)
    assert split.site_kw == 8
    assert split.house_kw == 2
    assert split.ev_grid_kw == 6
    route = _route(snap, stored=8, target=6)
    assert route.ev_grid_kwh == 6
    assert route.battery_to_home_kwh == 2
    assert route.grid_import_kwh == 6
    assert route.battery_stored_kwh == 6


def test_unproven_ev_membership_falls_back_without_double_counting():
    snap = _snapshot(house=8, ev_charging=True, ev_power_kw=6.0)
    route = _route(snap, stored=8, target=6)
    assert not route.ev_separation_proven
    assert route.battery_to_home_kwh == 0
    assert route.grid_import_kwh == 8
    assert route.ev_grid_kwh == 0  # No false attribution to a separate stream.


def test_connected_ev_missing_power_cannot_be_assumed_grid_isolated():
    snap = _snapshot(
        house=8,
        soc=55,
        ev_connected=True,
        ev_charging=None,
        ev_power_kw=None,
    )
    split = split_no_export_demand(snap, 8)
    assert not split.ev_separation_proven
    route = _route(snap, stored=5.5, target=6)
    assert route.battery_to_home_kwh == 0
    assert route.grid_to_battery_input_kwh == 0
    assert route.ev_grid_kwh == 0
    state = ControlEngine().plan(
        snap, _simulation(), snap.timestamp, _config(mode="control")
    )
    assert state.desired_charge_power_kw == 0
    assert state.desired_battery_to_home_power_kw == 0
    assert "ev_isolation_fallback" in state.operating_reason


def test_extra_slot_protection_only_replenishes_shortfall():
    snap = _snapshot(
        when=EXTRA,
        house=2,
        ev_charging=True,
        ev_power_kw=6,
        ev_load_in_house_load=False,
    )
    enough = _route(snap, stored=8, target=6)
    assert enough.kind == "extra_intelligent"
    assert enough.battery_to_home_kwh == 2
    assert enough.grid_to_battery_input_kwh == 0
    assert enough.grid_import_kwh == 6
    short = _route(snap, stored=5.5, target=6)
    assert short.battery_to_home_kwh == 0
    assert short.grid_to_battery_input_kwh == pytest.approx(0.5)
    assert short.grid_import_kwh == pytest.approx(8.5)


def test_solar_goes_to_house_then_natural_battery_charge():
    snap = _snapshot(house=1.0)
    route = _route(snap, solar=3.0, stored=7.0, target=6.0)
    assert route.solar_to_home_kwh == 1
    assert route.solar_to_battery_input_kwh == 2
    assert route.battery_stored_kwh == 9
    assert route.grid_import_kwh == 0


def test_shadow_floor_discharge_and_live_ev_fallback_are_separate():
    snap = _snapshot(
        house=8,
        ev_charging=True,
        ev_power_kw=6,
        ev_load_in_house_load=True,
    )
    shadow = ControlEngine().plan(snap, _simulation(), snap.timestamp, _config())
    assert shadow.desired_battery_to_home_power_kw == 2.0
    assert shadow.desired_min_soc_percent == 60
    assert shadow.desired_battery_export_power_kw == 0
    live = ControlEngine().plan(
        snap, _simulation(), snap.timestamp, _config(mode="control")
    )
    assert live.desired_battery_to_home_power_kw == 0
    assert live.desired_min_soc_percent == 80
    assert "ev_isolation_fallback" in live.operating_reason
    assert "KH7" in live.next_action


def test_physical_soc_wins_over_divergent_simulated_soc():
    snap = _snapshot(soc=80)
    state = ControlEngine().plan(
        snap, _simulation(simulated_battery_soc=10), snap.timestamp, _config()
    )
    assert state.desired_min_soc_percent == 60
    assert state.desired_charge_power_kw == 0
    assert state.desired_battery_to_home_power_kw == 1


def test_extra_missing_forecast_or_ev_scope_cannot_request_charge():
    snap = _snapshot(when=EXTRA, soc=55)
    no_forecast = ControlEngine().plan(
        snap,
        _simulation(home_reserve_forecast_source="unavailable"),
        snap.timestamp,
        _config(),
    )
    assert no_forecast.desired_charge_power_kw == 0
    unknown_scope = replace(snap, ev_charging=True, ev_power_kw=None)
    missing_power = ControlEngine().plan(
        unknown_scope, _simulation(), snap.timestamp, _config(mode="control")
    )
    assert missing_power.desired_charge_power_kw == 0
    assert missing_power.desired_battery_to_home_power_kw == 0


def test_physical_site_balance_only_produces_candidate_not_live_authority():
    common = dict(
        ev_kw=6,
        solar_kw=0,
        battery_kw=1,
        grid_import_kw=7,
        grid_export_kw=0,
        battery_positive_is_discharge=True,
    )
    assert infer_ev_load_in_house_load(house_kw=8, **common) is True
    assert infer_ev_load_in_house_load(house_kw=2, **common) is False
    assert infer_ev_load_in_house_load(house_kw=None, **common) is None


def test_power_down_island_and_emergency_take_priority_over_cheap_route():
    snap = _snapshot(saving_session_active=True)
    power_down = ControlEngine().plan(
        snap, _simulation(), snap.timestamp, _config(mode="control")
    )
    assert power_down.operating_reason == "awaiting_export_tariff_power_down"
    assert power_down.desired_charge_power_kw == 0
    assert power_down.desired_ev_charging_allowed is False

    island = ControlEngine().plan(
        _snapshot(),
        _simulation(),
        OVERNIGHT,
        replace(_config(mode="control"), virtual_scenario="grid_outage_night"),
    )
    assert island.island_mode_active
    assert island.desired_charge_power_kw == 0
    assert island.desired_ev_charging_allowed is False

    emergency = ControlEngine().plan(
        _snapshot(),
        _simulation(),
        OVERNIGHT,
        replace(_config(mode="control"), emergency_stop=True),
    )
    assert emergency.operating_reason == "emergency_stop"
    assert emergency.desired_charge_power_kw == 0


def test_paid_export_path_still_uses_original_cheap_charge():
    snap = _snapshot()
    state = ControlEngine().plan(
        snap, SimulationState(no_export_mode_active=False), snap.timestamp, _config()
    )
    assert state.operating_reason == "confirmed_cheap_charge"
    assert state.desired_work_mode == "Force Charge"
