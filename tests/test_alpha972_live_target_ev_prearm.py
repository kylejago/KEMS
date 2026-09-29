"""Alpha9.72 live No-export target parity and EV pre-arm regressions."""

from __future__ import annotations

from datetime import datetime
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

WHEN = datetime(2026, 9, 29, 22, 0, tzinfo=ZoneInfo("Europe/London"))


def _simulation_config() -> SimulationConfig:
    return SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=15.0,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_tariff_status="awaiting",
        site_import_limit_kw=14.5,
    )


def _control_config() -> ControlConfig:
    return ControlConfig(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        normal_reserve_percent=15.0,
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        site_import_limit_kw=14.5,
    )


def _snapshot(*, cheap: bool, soc: float = 45.0) -> Snapshot:
    return Snapshot(
        timestamp=WHEN,
        off_peak=cheap,
        ev_connected=True,
        ev_charging=False,
        ev_power_kw=0.0,
        ev_power_age_seconds=5.0,
        house_load_kw=0.6,
        solar_power_kw=0.0,
        grid_import_kw=0.0,
        grid_export_kw=0.0,
        battery_soc=soc,
        forecast_required_morning_soc_percent=51.1,
        forecast_recharge_target_feasible=True,
        stale_fields=(),
        source_data_age_seconds=5.0,
    )


def test_daytime_no_export_target_is_published_from_forecast() -> None:
    engine = SimulationEngine()
    config = _simulation_config()
    snapshot = _snapshot(cheap=False)

    state = engine._empty_current_state(
        snapshot,
        [snapshot],
        config,
        forecast_energy_until_offpeak_kwh=2.0,
    )

    assert state.no_export_mode_active is True
    assert state.overnight_charge_target_percent == 51.1
    assert state.overnight_charge_target_kwh == pytest.approx(
        round(config.battery_capacity_kwh * 0.511, 3)
    )


def test_confirmed_cheap_live_view_uses_same_forecast_target() -> None:
    engine = SimulationEngine()
    config = _simulation_config()
    snapshot = _snapshot(cheap=True)
    base = SimulationState(
        no_export_mode_active=True,
        overnight_charge_target_percent=24.1,
    )

    live = engine.legacy_no_export_control_view(
        snapshot,
        [snapshot],
        config,
        forecast_energy_until_offpeak_kwh=2.0,
        simulation=base,
    )

    assert live.overnight_charge_target_percent == 51.1
    assert live.home_reserve_forecast_source == "forecast_required_morning_soc"

    control = ControlEngine().plan(
        snapshot,
        live,
        snapshot.timestamp,
        _control_config(),
    )
    assert control.desired_work_mode == "Force Charge"
    assert control.desired_charge_power_kw == 7.0
    assert control.desired_min_soc_percent == 52.0


def test_forecast_target_falls_back_to_existing_no_export_rule_when_missing() -> None:
    engine = SimulationEngine()
    config = _simulation_config()
    snapshot = _snapshot(cheap=True)
    snapshot.forecast_required_morning_soc_percent = None
    base = SimulationState(no_export_mode_active=True)

    live = engine.legacy_no_export_control_view(
        snapshot,
        [snapshot],
        config,
        forecast_energy_until_offpeak_kwh=2.0,
        simulation=base,
    )

    assert live.overnight_charge_target_percent is not None
    assert live.overnight_charge_target_percent != 51.1
