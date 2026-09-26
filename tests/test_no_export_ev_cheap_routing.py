"""Draft no-export EV/grid-only cheap routing: simulation-only proof.

The live FoxESS write scope is deliberately unchanged until physical EV/grid
separation can be proven with fresh independent measurements.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from kems_core import SimulationConfig, SimulationEngine, Snapshot
from kems_core.no_export_cheap_policy import route_no_export_cheap

LONDON = ZoneInfo("Europe/London")


def _flow(**overrides):
    values = dict(
        whole_site_load_kw=8.0,  # Includes a 7 kW EV and 1 kW house.
        ev_power_kw=7.0,
        ev_charging=True,
        ev_power_stale=False,
        solar_kw=0.0,
        battery_stored_kwh=80.0,
        target_stored_kwh=60.0,
        reserve_kwh=10.0,
        capacity_kwh=100.0,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        site_import_limit_kw=14.5,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        hours=1.0,
    )
    values.update(overrides)
    return route_no_export_cheap(**values)


def test_above_target_battery_powers_house_only_and_ev_stays_on_grid() -> None:
    flow = _flow()
    assert flow.ev_evidence_valid
    assert flow.grid_to_ev_kwh == 7.0
    assert flow.grid_to_home_kwh == 0.0
    assert flow.grid_to_battery_input_kwh == 0.0
    assert flow.battery_to_home_kwh == 1.0
    assert flow.grid_import_kwh == 7.0
    assert flow.battery_stored_kwh == pytest.approx(80.0 - 1.0 / 0.95)


def test_target_is_a_floor_not_a_forced_discharge_destination() -> None:
    flow = _flow(whole_site_load_kw=7.0)
    assert flow.battery_to_home_kwh == 0.0
    assert flow.battery_stored_kwh == 80.0
    assert flow.grid_import_kwh == 7.0


def test_reaching_target_holds_battery_and_grid_covers_house_and_ev() -> None:
    flow = _flow(battery_stored_kwh=60.0)
    assert flow.battery_to_home_kwh == 0.0
    assert flow.grid_to_home_kwh == 1.0
    assert flow.grid_to_ev_kwh == 7.0
    assert flow.grid_import_kwh == 8.0
    assert flow.battery_stored_kwh == 60.0


def test_below_target_grid_charges_after_ev_and_house_within_site_limit() -> None:
    flow = _flow(battery_stored_kwh=50.0, site_import_limit_kw=9.0)
    assert flow.battery_to_home_kwh == 0.0
    assert flow.grid_to_ev_kwh == 7.0
    assert flow.grid_to_home_kwh == 1.0
    assert flow.grid_to_battery_input_kwh == 1.0
    assert flow.grid_import_kwh == 9.0
    assert flow.battery_stored_kwh == pytest.approx(50.95)


def test_solar_supplies_house_and_surplus_charges_battery_not_ev() -> None:
    flow = _flow(solar_kw=3.0)
    assert flow.grid_to_ev_kwh == 7.0
    assert flow.solar_to_home_kwh == 1.0
    assert flow.solar_to_battery_input_kwh == 2.0
    assert flow.battery_to_home_kwh == 0.0
    assert flow.grid_import_kwh == 7.0
    assert flow.battery_stored_kwh == pytest.approx(81.9)


@pytest.mark.parametrize(
    "ev_kw,stale",
    [(None, False), (7.0, True), (9.0, False)],
)
def test_unknown_or_inconsistent_ev_split_fails_closed(ev_kw, stale) -> None:
    flow = _flow(ev_power_kw=ev_kw, ev_power_stale=stale, battery_stored_kwh=50)
    assert not flow.ev_evidence_valid
    assert flow.battery_to_home_kwh == 0.0
    assert flow.grid_to_battery_input_kwh == 0.0
    assert flow.grid_import_kwh >= 8.0


def test_no_ev_house_only_routing_never_exports_battery() -> None:
    flow = _flow(whole_site_load_kw=1.0, ev_charging=False, ev_power_kw=0.0)
    assert flow.grid_to_ev_kwh == 0.0
    assert flow.battery_to_home_kwh == 1.0
    assert flow.grid_import_kwh == 0.0


def _snapshot(*, overnight: bool, soc: float, ev: bool = True) -> Snapshot:
    if overnight:
        now = datetime(2026, 9, 26, 23, 45, tzinfo=LONDON)
        end = datetime(2026, 9, 27, 5, 30, tzinfo=LONDON)
        next_cheap = datetime(2026, 9, 27, 23, 30, tzinfo=LONDON)
    else:
        now = datetime(2026, 9, 26, 18, 0, tzinfo=LONDON)
        end = datetime(2026, 9, 26, 19, 0, tzinfo=LONDON)
        next_cheap = datetime(2026, 9, 26, 23, 30, tzinfo=LONDON)
    return Snapshot(
        timestamp=now,
        current_import_rate=3.4933,
        off_peak=overnight,
        intelligent_slot=not overnight,
        intelligent_slot_evidence={"large_import_permitted": True},
        ev_charging=ev,
        ev_power_kw=7.0 if ev else 0.0,
        house_load_kw=8.0 if ev else 1.0,
        solar_power_kw=0.0,
        battery_soc=soc,
        next_offpeak_start=next_cheap,
        offpeak_end=end,
    )


def _config(*, paid=False) -> SimulationConfig:
    return SimulationConfig(
        battery_capacity_kwh=100.0,
        battery_reserve_percent=15.0,
        battery_initial_percent=80.0,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        site_import_limit_kw=14.5,
        proposal_solar_enabled=False,
        export_tariff_status="active" if paid else "awaiting",
    )


def _plan(snapshot, *, stored, learned):
    engine = SimulationEngine()
    return engine._current_plan(
        snapshot,
        [snapshot],
        stored,
        15.0,
        100.0,
        _config(),
        learned,
    )


def test_overnight_current_plan_discharge_stops_at_floor_not_at_start_soc() -> None:
    snapshot = _snapshot(overnight=True, soc=80.0)
    plan = _plan(snapshot, stored=80.0, learned=50.0)
    assert plan["overnight_charge_target_percent"] < 80.0
    assert plan["battery_to_home"] == 1.0
    assert plan["grid_import"] == 7.0
    assert plan["grid_export"] == 0.0
    assert plan["battery_export"] == 0.0


def test_daytime_extra_slot_uses_next_cheap_requirement() -> None:
    snapshot = _snapshot(overnight=False, soc=10.0)
    assert snapshot.cheap_period_confirmed
    plan = _plan(snapshot, stored=10.0, learned=10.0)
    assert plan["overnight_charge_target_percent"] > 15.0
    assert plan["battery_to_home"] == 0.0
    assert plan["battery_charge"] > 0.0
    assert plan["grid_import"] == 14.5
    assert plan["grid_export"] == 0.0


def test_extra_slot_with_surplus_soc_uses_battery_for_house_only() -> None:
    snapshot = _snapshot(overnight=False, soc=80.0)
    plan = _plan(snapshot, stored=80.0, learned=10.0)
    assert plan["battery_charge"] == 0.0
    assert plan["battery_to_home"] == 1.0
    assert plan["grid_import"] == 7.0


def test_paid_export_cheap_branch_retains_full_kems_routing() -> None:
    snapshot = _snapshot(overnight=True, soc=80.0)
    plan = SimulationEngine()._current_plan(
        snapshot,
        [snapshot],
        80.0,
        15.0,
        100.0,
        _config(paid=True),
        50.0,
    )
    assert plan["battery_to_home"] == 0.0
    assert plan["battery_charge"] == 6.5
    assert plan["grid_import"] == 14.5
    assert plan["grid_export"] == 0.0


def test_retained_no_export_replay_excludes_ev_from_battery_discharge() -> None:
    start = _snapshot(overnight=True, soc=95.0)
    stop = Snapshot(
        timestamp=start.timestamp + timedelta(minutes=10),
        house_load_kw=8.0,
        solar_power_kw=0.0,
        current_import_rate=3.4933,
    )
    result = SimulationEngine().simulate_today(
        [start, stop],
        stop.timestamp,
        _config(),
        forecast_energy_until_offpeak_kwh=50.0,
        current_snapshot=stop,
    )
    assert result.simulated_battery_to_home_kwh == 0.167
    assert result.simulated_grid_import_kwh == 1.167
    assert result.simulated_battery_export_kwh == 0.0
    assert result.simulated_grid_export_kwh == 0.0
