"""Alpha9.69 proposed No paid export cheap routing — no hardware proof claims."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from kems_core import (
    ControlConfig,
    ControlEngine,
    SimulationConfig,
    SimulationEngine,
    SimulationState,
    Snapshot,
)
from kems_core.control_write_authority import assess_foxess_control_write_authority
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
    state = ControlEngine().plan(snap, _simulation(), snap.timestamp, _config())
    assert state.desired_charge_power_kw == 0
    assert state.desired_battery_to_home_power_kw == 0
    assert state.alpha969_routing_shadow_only is True
    assert state.operating_reason == "no_export_overnight"


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
    assert live.operating_reason == "awaiting_export_tariff_charge"
    assert live.desired_work_mode == "Self Use"
    assert live.alpha969_routing_shadow_only is False
    assert live.desired_charge_power_kw == 0
    assert live.commands_permitted is False


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
        unknown_scope, _simulation(), snap.timestamp, _config()
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


@pytest.mark.parametrize("included,load", [(True, 8.0), (False, 2.0)])
def test_no_export_day_replay_never_battery_supplies_ev_or_counts_twice(included, load):
    records = [
        _snapshot(
            when=EXTRA + timedelta(minutes=30 * i),
            house=load,
            soc=80.0,
            off_peak=False,
            current_import_rate=28.3,
            ev_charging=True,
            ev_power_kw=6.0,
            ev_load_in_house_load=included,
            grid_import_kw=6.0,
        )
        for i in range(3)
    ]
    result = SimulationEngine().simulate_today(
        records,
        records[-1].timestamp + timedelta(minutes=1),
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_reserve_percent=10.0,
            battery_initial_percent=80.0,
            max_charge_kw=7.0,
            max_discharge_kw=7.0,
            charge_efficiency=1.0,
            discharge_efficiency=1.0,
            proposal_solar_enabled=False,
            export_tariff_status="awaiting",
            saving_session_enabled=False,
        ),
    )
    assert result.actual_house_consumption_kwh == 8.0
    assert result.actual_ev_energy_kwh == 6.0
    assert result.simulated_ev_grid_import_kwh == 6.0
    assert result.simulated_battery_to_home_kwh == 2.0
    assert result.simulated_grid_import_kwh == 6.0
    assert result.current_simulated_house_load_kw == 8.0
    assert result.current_simulated_non_ev_house_load_kw == 2.0
    assert result.current_simulated_ev_grid_import_kw == 6.0
    assert result.current_simulated_battery_to_home_power_kw == 2.0
    assert result.current_simulated_grid_import_kw == 6.0
    assert result.no_export_ev_load_proven is True


def test_no_export_day_replay_unproven_ev_scope_has_no_false_attribution():
    records = [
        _snapshot(
            when=EXTRA + timedelta(minutes=30 * i),
            house=8.0,
            soc=80.0,
            off_peak=False,
            current_import_rate=28.3,
            ev_charging=True,
            ev_power_kw=6.0,
            ev_load_in_house_load=None,
        )
        for i in range(3)
    ]
    result = SimulationEngine().simulate_today(
        records,
        records[-1].timestamp + timedelta(minutes=1),
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_reserve_percent=10.0,
            battery_initial_percent=80.0,
            proposal_solar_enabled=False,
            export_tariff_status="awaiting",
            saving_session_enabled=False,
        ),
    )
    assert result.simulated_ev_grid_import_kwh is None
    assert result.simulated_battery_to_home_kwh == 0.0
    assert result.simulated_grid_import_kwh == 8.0
    assert result.current_simulated_ev_grid_import_kw is None
    assert result.current_simulated_non_ev_house_load_kw is None
    assert result.no_export_ev_load_proven is False
    assert result.no_export_ev_scope_reason == "EV/load measurement scope unproven"


def test_ev_scope_is_not_claimed_proven_just_because_charger_is_idle():
    snap = _snapshot(
        when=EXTRA,
        house=2.0,
        off_peak=False,
        ev_connected=False,
        ev_charging=False,
        ev_power_kw=0.0,
    )
    result = SimulationEngine()._empty_current_state(
        snap,
        [snap],
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=80.0,
            proposal_solar_enabled=False,
            export_tariff_status="awaiting",
        ),
    )
    assert result.current_simulated_ev_grid_import_kw == 0.0
    assert result.current_simulated_non_ev_house_load_kw == 2.0
    assert result.no_export_ev_load_proven is False
    assert result.no_export_ev_scope_reason == "EV not charging"


def test_extra_slot_missing_forward_deadline_does_not_grid_charge_twin():
    snap = _snapshot(
        when=EXTRA,
        house=2.0,
        off_peak=True,
        next_offpeak_start=None,
        ev_charging=True,
        ev_power_kw=6.0,
        ev_load_in_house_load=False,
    )
    result = SimulationEngine()._empty_current_state(
        snap,
        [snap],
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_reserve_percent=10.0,
            battery_initial_percent=20.0,
            proposal_solar_enabled=False,
            export_tariff_status="awaiting",
        ),
    )
    assert result.no_export_cheap_policy == "extra_intelligent"
    assert result.current_simulated_battery_charge_power_kw == 0.0
    assert result.home_reserve_forecast_source == "unavailable"
    assert result.current_simulated_ev_grid_import_kw == 6.0


def test_no_export_missing_grid_meter_fallback_counts_external_ev_once():
    records = [
        _snapshot(
            when=EXTRA + timedelta(minutes=30 * i),
            house=2.0,
            soc=80.0,
            off_peak=False,
            current_import_rate=28.3,
            solar_power_kw=0.0,
            grid_import_kw=None,
            ev_charging=True,
            ev_power_kw=6.0,
            ev_load_in_house_load=False,
        )
        for i in range(3)
    ]
    result = SimulationEngine().simulate_today(
        records,
        records[-1].timestamp + timedelta(minutes=1),
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=80.0,
            proposal_solar_enabled=False,
            export_tariff_status="awaiting",
            saving_session_enabled=False,
        ),
    )
    assert result.actual_house_consumption_kwh == 8.0
    assert result.actual_grid_import_kwh == 8.0
    assert result.actual_ev_energy_kwh == 6.0
    assert result.baseline_no_system_cost_pence == 226.4


def test_no_export_ev_accounting_does_not_change_paid_export_replay():
    records = [
        _snapshot(
            when=EXTRA + timedelta(minutes=30 * i),
            house=2.0,
            soc=80.0,
            off_peak=False,
            current_import_rate=28.3,
            ev_charging=True,
            ev_power_kw=6.0,
            ev_load_in_house_load=False,
        )
        for i in range(3)
    ]
    result = SimulationEngine().simulate_today(
        records,
        records[-1].timestamp + timedelta(minutes=1),
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=80.0,
            proposal_solar_enabled=False,
            export_tariff_status="active",
            saving_session_enabled=False,
        ),
    )
    assert result.actual_house_consumption_kwh == 2.0
    assert result.simulated_ev_grid_import_kwh is None
    assert result.current_simulated_ev_grid_import_kw is None


@pytest.mark.parametrize("included,load", [(True, 8.0), (False, 2.0)])
def test_no_export_future_house_forecast_excludes_verified_ev(included, load):
    next_cheap = EXTRA + timedelta(hours=9, minutes=30)
    records = [
        _snapshot(
            when=EXTRA + timedelta(minutes=15 * i),
            house=load,
            ev_charging=True,
            ev_power_kw=6.0,
            ev_load_in_house_load=included,
            next_offpeak_start=next_cheap,
        )
        for i in range(3)
    ]
    net, source, home, solar, credit = SimulationEngine()._no_export_home_forecast(
        records[-1],
        records,
        SimulationConfig(proposal_solar_enabled=False, export_tariff_status="awaiting"),
        forecast_energy_until_offpeak_kwh=80.0,
    )
    assert source == "recent_non_ev_average"
    assert home == pytest.approx(18.0)
    assert solar == 0.0
    assert credit == 0.0
    assert net == pytest.approx(19.8)


def test_extra_slot_with_one_sample_carries_usable_forecast_to_control():
    snap = _snapshot(
        when=EXTRA,
        house=0.5,
        soc=20.0,
        next_offpeak_start=EXTRA + timedelta(hours=3),
        offpeak_end=EXTRA + timedelta(hours=1),
        ev_charging=True,
        ev_power_kw=6.0,
        ev_load_in_house_load=False,
    )
    simulation = SimulationEngine()._empty_current_state(
        snap,
        [snap],
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_reserve_percent=10.0,
            battery_initial_percent=20.0,
            proposal_solar_enabled=False,
            export_tariff_status="awaiting",
        ),
        forecast_energy_until_offpeak_kwh=40.0,
    )
    assert simulation.home_reserve_forecast_source == "recent_non_ev_average"
    assert simulation.forecast_home_until_next_cheap_kwh == pytest.approx(1.0)
    assert simulation.overnight_charge_target_percent < 50.0
    state = ControlEngine().plan(snap, simulation, snap.timestamp, _config())
    assert state.operating_reason == "no_export_extra_slot"
    assert state.alpha969_routing_shadow_only is True
    assert state.desired_charge_power_kw > 0
    assert state.desired_charge_power_kw < 7
    assert state.desired_battery_to_home_power_kw == 0


def test_no_export_ev_overlay_blocks_stale_connected_ev_outside_cheap():
    snap = _snapshot(
        when=EXTRA,
        house=3.0,
        off_peak=False,
        ev_connected=True,
        ev_charging=None,
        ev_power_kw=None,
    )
    plan = ControlEngine().plan(
        snap,
        _simulation(
            current_simulated_house_load_kw=3.0,
            current_simulated_battery_to_home_power_kw=3.0,
        ),
        snap.timestamp,
        _config(mode="control"),
    )
    assert plan.desired_battery_to_home_power_kw == 0.0
    assert plan.desired_total_discharge_power_kw == 0.0
    assert plan.desired_battery_export_power_kw == 0.0


def test_paid_export_path_still_uses_original_cheap_charge():
    snap = _snapshot()
    state = ControlEngine().plan(
        snap, SimulationState(no_export_mode_active=False), snap.timestamp, _config()
    )
    assert state.operating_reason == "confirmed_cheap_charge"
    assert state.desired_work_mode == "Force Charge"


def test_alpha969_evidence_is_visible_without_confusing_it_with_live_authority():
    root = Path(__file__).parents[1] / "custom_components" / "kems"
    sensor = (root / "sensor.py").read_text(encoding="utf-8")
    binary = (root / "binary_sensor.py").read_text(encoding="utf-8")
    for key in (
        "simulated_ev_grid_import_kwh",
        "current_simulated_site_load_kw",
        "current_simulated_non_ev_house_load_kw",
        "current_simulated_ev_grid_import_kw",
        "no_export_cheap_policy",
        "no_export_ev_load_proven",
        "no_export_ev_scope_reason",
        "no_export_ev_isolation_physically_proven",
    ):
        assert f'"{key}"' in sensor
    assert '"no_export_ev_isolation_physically_proven": False' in sensor
    assert 'key="alpha969_routing_shadow_only"' in binary
    assert "data.control.alpha969_routing_shadow_only" in binary
    assert 'key="no_export_ev_load_scope_identified"' in binary
    assert "data.simulation.no_export_ev_load_proven" in binary


@pytest.mark.parametrize(
    ("soc", "expected_mode", "expected_charge"),
    [
        (55.0, "Force Charge", 7.0),
        (60.0, "Self Use", 0.0),
        (80.0, "Self Use", 0.0),
    ],
)
def test_alpha969_shadow_never_displaces_reviewed_live_cheap_charge(
    soc, expected_mode, expected_charge
):
    snap = _snapshot(
        soc=soc,
        house=8.0,
        ev_charging=True,
        ev_power_kw=6.0,
        ev_load_in_house_load=True,
    )
    sim = _simulation(
        target=60.0,
        current_simulated_grid_bypass_power_kw=7.0,
    )
    engine = ControlEngine()
    proposal = engine.plan(snap, sim, snap.timestamp, _config())
    live = engine.plan(snap, sim, snap.timestamp, _config(mode="control"))
    assert proposal.alpha969_routing_shadow_only is True
    assert proposal.operating_reason == "no_export_overnight"
    assert live.alpha969_routing_shadow_only is False
    assert live.operating_reason == "awaiting_export_tariff_charge"
    assert live.desired_work_mode == expected_mode
    assert live.desired_charge_power_kw == expected_charge
    assert live.desired_min_soc_percent == max(soc, 60.0)
    assert live.grid_bypass_power_kw == 7.0
    assert live.total_site_import_kw == 7.0 + expected_charge

    kwargs = dict(
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=True,
        cheap_period_confirmed=True,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
    )
    old_authority = assess_foxess_control_write_authority(live, **kwargs)
    new_authority = assess_foxess_control_write_authority(proposal, **kwargs)
    assert old_authority.commands_permitted is True
    assert old_authority.action == ("force_charge" if expected_charge else "self_use")
    assert new_authority.commands_permitted is False
    assert new_authority.action == "release"


def test_live_plan_and_independent_shadow_preview_are_not_cross_wired() -> None:
    root = Path(__file__).parents[1] / "custom_components" / "kems"
    coordinator = (root / "coordinator.py").read_text(encoding="utf-8")
    control = (root / "kems_core" / "control.py").read_text(encoding="utf-8")
    data = (root / "kems_core" / "models.py").read_text(encoding="utf-8")
    assert 'mode != "control"' in control
    assert 'replace(self.settings.control, operating_mode="shadow")' in coordinator
    assert '"hardware_write_authorised": False' in coordinator
    assert "alpha969_shadow_plan=alpha969_shadow_plan" in coordinator
    assert (
        "control = apply_happy_hour_control(control, snapshot, happy_hour_plan)"
        in coordinator
    )
    assert "control=control,\n                technical_ready=" in coordinator
    assert "control=proposal,\n                technical_ready=" not in coordinator
    assert "alpha969_shadow_plan: dict[str, Any]" in data
    assert 'key="alpha969_shadow_proposal"' in (root / "sensor.py").read_text(
        encoding="utf-8"
    )
    assert '"alpha969_shadow_plan": dict(data.alpha969_shadow_plan)' in (
        root / "diagnostics.py"
    ).read_text(encoding="utf-8")


def test_alpha969_release_identity_is_explicitly_shadow_only() -> None:
    root = Path(__file__).parents[1]
    manifest = json.loads(
        (root / "custom_components" / "kems" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    bundle = json.loads(
        (root / "release" / "kems-bundle.template.json").read_text(
            encoding="utf-8"
        )
    )
    reason = bundle["maintenance"]["reason"]
    assert manifest["version"] == "0.9.0-alpha9.69"
    assert reason.startswith("Alpha9.69 adds a shadow-only No Paid Export")
    assert "Alpha9.68 Control-mode cheap-period planner" in reason
    assert "No new KH7 output control" in reason
    assert bundle["components"]["property_web"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.3"
