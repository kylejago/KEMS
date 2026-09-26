"""Alpha9.69 no-export selective cheap-routing simulation and live floor tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from kems_core import (
    ControlConfig,
    ControlEngine,
    SimulationConfig,
    SimulationState,
    Snapshot,
)
from kems_core.simulation import SimulationEngine, _no_export_cheap_route

NOW = datetime(2026, 9, 26, 23, 30, tzinfo=UTC)


def _config(**changes) -> SimulationConfig:
    return SimulationConfig(
        battery_capacity_kwh=100.0,
        battery_reserve_percent=15.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        site_import_limit_kw=14.5,
        proposal_solar_enabled=False,
        export_tariff_status="awaiting",
        **changes,
    )


def _snapshot(*, load: float = 8.0, ev: float = 7.0, solar: float = 0.0) -> Snapshot:
    return Snapshot(
        timestamp=NOW,
        current_import_rate=3.4933,
        off_peak=True,
        offpeak_end=NOW + timedelta(hours=6),
        next_offpeak_start=NOW + timedelta(hours=24),
        house_load_kw=load,
        ev_charging=ev > 0,
        ev_power_kw=ev,
        solar_power_kw=solar,
        battery_soc=80.0,
        grid_import_kw=0.0,
    )


def test_overnight_above_target_discharge_is_house_only_and_never_export() -> None:
    snapshot = _snapshot()
    result = _no_export_cheap_route(snapshot, 8.0, 0.0, 80.0, 60.0, 100.0, _config())
    assert result["ev_grid"] == 7.0
    assert result["battery_home"] == 1.0
    assert result["grid_home"] == 0.0
    assert result["grid_import"] == 7.0
    assert result["grid_charge_input"] == 0.0
    assert 60.0 < result["battery_after"] < 80.0


def test_target_is_floor_not_a_forced_discharge_destination() -> None:
    snapshot = _snapshot(load=7.0, ev=7.0)
    result = _no_export_cheap_route(snapshot, 7.0, 0.0, 80.0, 60.0, 100.0, _config())
    assert result["battery_home"] == 0.0
    assert result["battery_after"] == 80.0
    assert result["grid_import"] == 7.0


def test_at_target_grid_covers_ev_and_remaining_house() -> None:
    snapshot = _snapshot()
    result = _no_export_cheap_route(snapshot, 8.0, 0.0, 60.0, 60.0, 100.0, _config())
    assert result["battery_home"] == 0.0
    assert result["grid_home"] == 1.0
    assert result["ev_grid"] == 7.0
    assert result["grid_import"] == 8.0
    assert result["battery_after"] == 60.0


def test_below_target_charges_only_with_site_headroom() -> None:
    snapshot = _snapshot()
    result = _no_export_cheap_route(snapshot, 8.0, 0.0, 50.0, 60.0, 100.0, _config())
    assert result["battery_home"] == 0.0
    assert result["grid_charge_input"] == 6.5
    assert result["grid_import"] == 14.5
    assert result["battery_after"] == pytest.approx(56.175)


def test_extra_intelligent_slot_above_target_uses_grid_for_ev_only() -> None:
    snapshot = _snapshot()
    snapshot.off_peak = False
    snapshot.intelligent_slot = True
    snapshot.intelligent_slot_evidence = {"large_import_permitted": True}
    assert snapshot.cheap_period_confirmed is True
    result = _no_export_cheap_route(snapshot, 8.0, 0.0, 80.0, 60.0, 100.0, _config())
    assert result["battery_home"] == 1.0
    assert result["ev_grid"] == result["grid_import"] == 7.0
    assert result["grid_charge_input"] == 0.0


def test_solar_covers_house_and_surplus_charges_battery_not_ev() -> None:
    snapshot = _snapshot(solar=2.0)
    result = _no_export_cheap_route(snapshot, 8.0, 2.0, 80.0, 60.0, 100.0, _config())
    assert result["solar_home"] == 1.0
    assert result["solar_charge_input"] == 1.0
    assert result["ev_grid"] == result["grid_import"] == 7.0
    assert result["battery_home"] == 0.0


def test_unknown_ev_draw_fails_closed_in_simulation() -> None:
    snapshot = _snapshot()
    snapshot.ev_power_kw = None
    result = _no_export_cheap_route(snapshot, 8.0, 0.0, 80.0, 60.0, 100.0, _config())
    assert result["battery_home"] == 0.0
    assert result["ev_grid"] == 8.0


def test_current_plan_matches_selective_routing_and_keeps_target() -> None:
    snapshot = _snapshot()
    plan = SimulationEngine()._current_plan(
        snapshot, [snapshot], 80.0, 15.0, 100.0, _config(), 50.0
    )
    assert plan["battery_to_home"] == 1.0
    assert plan["grid_import"] == plan["grid_bypass"] == 7.0
    assert plan["battery_charge"] == 0.0
    assert plan["grid_export"] == plan["battery_export"] == 0.0
    assert plan["overnight_charge_target_percent"] < 80.0



def test_historical_no_export_replay_uses_ev_grid_and_house_battery() -> None:
    start = datetime(2026, 9, 26, 0, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start + timedelta(minutes=30 * i),
            current_import_rate=3.4933,
            off_peak=True,
            offpeak_end=start + timedelta(hours=6),
            next_offpeak_start=start + timedelta(hours=24),
            house_load_kw=8.0,
            ev_charging=True,
            ev_power_kw=7.0,
            solar_power_kw=0.0,
            battery_soc=80.0,
            grid_import_kw=7.0,
        )
        for i in range(3)
    ]
    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(hours=1),
        _config(),
        forecast_energy_until_offpeak_kwh=50.0,
        current_snapshot=records[-1],
    )
    assert result.no_export_mode_active is True
    assert result.simulated_cheap_import_kwh == 7.0
    assert result.simulated_battery_to_home_kwh == 1.0
    assert result.simulated_grid_export_kwh == 0.0
    assert result.simulated_battery_export_kwh == 0.0


def test_paid_export_cheap_plan_is_untouched() -> None:
    snapshot = _snapshot()
    paid = SimulationConfig(
        battery_capacity_kwh=100.0,
        battery_reserve_percent=15.0,
        proposal_solar_enabled=False,
        export_tariff_status="active",
        max_charge_kw=7.0,
        inverter_limit_kw=7.0,
        site_import_limit_kw=14.5,
    )
    plan = SimulationEngine()._current_plan(
        snapshot, [snapshot], 80.0, 15.0, 100.0, paid, 50.0
    )
    assert plan["battery_to_home"] == 0.0
    assert plan["grid_bypass"] == 8.0
    assert plan["battery_charge"] == 6.5
    assert plan["grid_import"] == 14.5


def test_live_no_ev_uses_target_min_soc_not_current_soc() -> None:
    snapshot = _snapshot(load=1.0, ev=0.0)
    simulation = SimulationState(
        ready=True,
        no_export_mode_active=True,
        overnight_charge_target_percent=60.0,
        current_simulated_grid_bypass_power_kw=0.0,
    )
    config = ControlConfig(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        normal_reserve_percent=15.0,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=6.4,
        eps_limit_kw=7.0,
        site_import_limit_kw=14.5,
    )
    control = ControlEngine().plan(snapshot, simulation, NOW, config)
    assert control.desired_work_mode == "Self Use"
    assert control.desired_min_soc_percent == 60.0
    assert control.desired_charge_power_kw == 0.0
    assert control.desired_grid_export_allowed is False


def test_live_ev_charging_holds_soc_until_ev_isolation_is_proven() -> None:
    snapshot = _snapshot()
    simulation = SimulationState(
        ready=True,
        no_export_mode_active=True,
        overnight_charge_target_percent=60.0,
        current_simulated_grid_bypass_power_kw=7.0,
    )
    config = ControlConfig(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        normal_reserve_percent=15.0,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=6.4,
        eps_limit_kw=7.0,
        site_import_limit_kw=14.5,
    )
    control = ControlEngine().plan(snapshot, simulation, NOW, config)
    assert control.desired_work_mode == "Self Use"
    assert control.desired_min_soc_percent == 80.0
    assert "cannot isolate EV" in control.next_action
