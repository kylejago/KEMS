"""Alpha9.162: paid export has a 15% floor; home service has a 10% floor.

Use the real pure-core budget and final physical guard without HA hardware writes.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from kems_core import ControlConfig, ControlState, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import (
    allow_paid_agile_house_discharge_to_ten_percent,
    guard_paid_agile_physical_export,
    physically_exportable_paid_agile_energy_kwh,
)

CAPACITY = 56.42
SIM = SimulationConfig(
    battery_capacity_kwh=CAPACITY,
    battery_reserve_percent=15.0,
    discharge_efficiency=0.95,
)
CONTROL_CONFIG = ControlConfig(stale_data_seconds=180)
NOW = datetime(2026, 10, 30, 21, 5, tzinfo=UTC)


def _budget(stored: float, home: float, reserve: float = 15.0) -> float:
    return physically_exportable_paid_agile_energy_kwh(
        stored_kwh=stored,
        capacity_kwh=CAPACITY,
        export_reserve_percent=reserve,
        protected_house_kwh=home,
    )


def test_21_05_dual_floor_recovers_surplus_without_double_reserving() -> None:
    # 21:05 live diagnostic: 13.61 kWh physical, 4.84 kWh house reserve.
    expected = min(13.61 - CAPACITY * 0.15, 13.61 - CAPACITY * 0.10 - 4.84)
    assert _budget(13.61, 4.84) == pytest.approx(expected)
    assert _budget(13.61, 4.84) == pytest.approx(3.128, abs=0.01)


def test_paid_export_never_crosses_fifteen_percent() -> None:
    for soc in (15.0, 14.9, 10.0):
        assert _budget(CAPACITY * soc / 100.0, 0.0) == 0.0
    # Low forecast home demand still cannot justify export below 15%.
    assert _budget(CAPACITY * 0.16, 0.0) == pytest.approx(CAPACITY * 0.01)


def test_house_use_from_fifteen_to_ten_remains_protected() -> None:
    # The household has five percentage points below the export floor for
    # ordinary Self Use, but paid export must not consume it in advance.
    energy_at_25 = CAPACITY * 0.25
    five_percent_kwh = CAPACITY * 0.05
    assert _budget(energy_at_25, five_percent_kwh + 3.0) == pytest.approx(
        energy_at_25 - CAPACITY * 0.10 - (five_percent_kwh + 3.0)
    )
    assert _budget(energy_at_25, 20.0) == 0.0


def test_higher_configured_export_floor_still_wins() -> None:
    stored = CAPACITY * 0.30
    assert _budget(stored, 0, reserve=20.0) == pytest.approx(CAPACITY * 0.10)
    assert _budget(stored, 0, reserve=30.0) == 0.0


@pytest.mark.parametrize(
    ("stored", "capacity", "reserve", "home"),
    [
        (float("nan"), CAPACITY, 15.0, 1.0),
        (10.0, 0.0, 15.0, 1.0),
        (10.0, CAPACITY, float("nan"), 1.0),
        (10.0, CAPACITY, 15.0, -1.0),
        (CAPACITY + 1.0, CAPACITY, 15.0, 1.0),
    ],
)
def test_bad_physical_budget_inputs_fail_closed(
    stored, capacity, reserve, home
) -> None:
    assert (
        physically_exportable_paid_agile_energy_kwh(
            stored_kwh=stored,
            capacity_kwh=capacity,
            export_reserve_percent=reserve,
            protected_house_kwh=home,
        )
        == 0.0
    )


def _dispatch_control() -> ControlState:
    return ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_price_optimised",
        desired_work_mode="Force Discharge",
        desired_battery_to_home_power_kw=0.88,
        desired_battery_export_power_kw=6.4,
        desired_total_discharge_power_kw=7.28,
        desired_grid_export_allowed=True,
        data_fresh=True,
        plan_safe=True,
    )


def _dispatch_snapshot(soc: float) -> Snapshot:
    return Snapshot(
        timestamp=NOW,
        battery_soc=soc,
        house_load_kw=0.88,
        ev_connected=False,
        ev_charging=False,
        source_data_age_seconds=2.0,
        source_age_seconds={"battery_soc": 2.0, "house_load_kw": 2.0},
        next_offpeak_start=NOW + timedelta(hours=2, minutes=25),
    )


def _dispatch(soc: float, forecast_kwh: float = 3.2):
    return guard_paid_agile_physical_export(
        _dispatch_control(),
        _dispatch_snapshot(soc),
        SimpleNamespace(
            ready=True,
            expected_house_remaining_today_kwh=forecast_kwh,
            expected_solar_remaining_today_kwh=0.0,
            confidence_percent=90.0,
        ),
        SIM,
        CONTROL_CONFIG,
        now=NOW,
    )


def test_live_guard_can_export_above_fifteen_while_protecting_ten_home() -> None:
    control, report = _dispatch(25.0)
    assert control.desired_battery_export_power_kw > 0.5
    assert report["house_floor_soc_percent"] == 10.0
    assert report["export_floor_soc_percent"] == 15.0
    assert report["protected_home_energy_kwh"] > 4.0
    assert control.desired_battery_export_power_kw <= 6.4


def test_live_guard_stops_export_at_fifteen_but_keeps_home_self_use() -> None:
    control, report = _dispatch(15.0)
    assert control.desired_battery_export_power_kw == 0.0
    assert control.desired_work_mode == "Self Use"
    assert control.desired_battery_to_home_power_kw == 0.88
    assert report["status"] == "blocked"


def test_live_guard_can_still_veto_with_large_house_demand() -> None:
    control, report = _dispatch(25.0, forecast_kwh=20.0)
    assert control.desired_battery_export_power_kw == 0.0
    assert report["status"] == "blocked"


def _house_only_control() -> ControlState:
    return replace(
        _dispatch_control(),
        desired_work_mode="Self Use",
        desired_battery_export_power_kw=0.0,
        desired_total_discharge_power_kw=0.88,
        desired_min_soc_percent=15.0,
    )


def _confirmed_unplugged_snapshot() -> Snapshot:
    return replace(
        _dispatch_snapshot(15.0),
        ev_power_kw=0.0,
        ev_power_age_seconds=2.0,
    )


def test_verified_house_only_self_use_requests_ten_percent_hardware_min_soc() -> None:
    control, applied = allow_paid_agile_house_discharge_to_ten_percent(
        _house_only_control(),
        _confirmed_unplugged_snapshot(),
        ev_export_safe=True,
        power_down_active=False,
    )
    assert applied is True
    assert control.desired_min_soc_percent == 10.0
    assert control.desired_work_mode == "Self Use"
    assert control.desired_battery_to_home_power_kw == 0.88


def test_active_export_retains_fifteen_percent_inverter_fail_safe() -> None:
    exporting = replace(_house_only_control(), desired_battery_export_power_kw=2.0)
    control, applied = allow_paid_agile_house_discharge_to_ten_percent(
        exporting, _confirmed_unplugged_snapshot(),
        ev_export_safe=True, power_down_active=False,
    )
    assert applied is False
    assert control.desired_min_soc_percent == 15.0


def test_ev_uncertainty_and_higher_priority_sessions_do_not_lower_hardware_min_soc() -> None:
    safe = _confirmed_unplugged_snapshot()
    cases = (
        (replace(safe, ev_connected=True), True, False),
        (replace(safe, ev_connected=None), True, False),
        (replace(safe, ev_charging=True), True, False),
        (replace(safe, ev_power_kw=3.0), True, False),
        (replace(safe, ev_power_age_seconds=300.0), True, False),
        (safe, False, False),
        (safe, True, True),
    )
    for snapshot, ev_safe, power_down in cases:
        result, applied = allow_paid_agile_house_discharge_to_ten_percent(
            _house_only_control(), snapshot,
            ev_export_safe=ev_safe,
            power_down_active=power_down,
        )
        assert applied is False
        assert result.desired_min_soc_percent == 15.0
