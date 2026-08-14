"""Tests for Full KEMS Forecast fusion and reserve planning."""

from datetime import UTC, datetime, timedelta

from kems_core import (
    ForecastConfig,
    ForecastHour,
    ForecastPlanningEngine,
    LearnedState,
    SimulationConfig,
    SimulationState,
    SolarForecastState,
    fuse_solar_forecasts,
)


def _hourly_solar(day: datetime, values: list[float]) -> tuple[ForecastHour, ...]:
    return tuple(
        ForecastHour(timestamp=day + timedelta(hours=hour), solar_energy_kwh=value)
        for hour, value in enumerate(values)
    )


def test_forecast_fusion_pulls_optimistic_primary_down_but_keeps_it_primary() -> None:
    now = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
    tomorrow = datetime(2026, 12, 2, 0, 0, tzinfo=UTC)
    state = fuse_solar_forecasts(
        now=now,
        forecast_solar_remaining_today_kwh=2.0,
        forecast_solar_tomorrow_kwh=10.0,
        forecast_solar_entity_count=2,
        open_meteo_remaining_today_kwh=1.0,
        open_meteo_tomorrow_kwh=4.0,
        hourly=_hourly_solar(tomorrow, [4 / 24] * 24),
    )
    assert state.source == "forecast_solar+open_meteo"
    assert state.expected_solar_tomorrow_kwh == 7.6
    assert 4.0 < state.expected_solar_tomorrow_kwh < 10.0
    assert abs(sum(item.solar_energy_kwh for item in state.hourly) - 7.6) < 0.02


def test_recharge_feasibility_reports_physical_81_percent_ceiling() -> None:
    now = datetime(2026, 12, 1, 18, 0, tzinfo=UTC)
    plan = ForecastPlanningEngine().plan(
        simulation=SimulationState(
            simulated_battery_soc=10.0,
            projected_soc_at_cheap_period_percent=10.0,
        ),
        learned=LearnedState(
            predicted_house_energy_tomorrow_kwh=20.0,
            predicted_house_energy_remaining_today_kwh=None,
        ),
        forecast=SolarForecastState(
            ready=True,
            source="forecast_solar+open_meteo",
            expected_solar_tomorrow_kwh=5.0,
            last_updated=now,
        ),
        simulation_config=SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_initial_percent=10.0,
            battery_reserve_percent=10.0,
            max_charge_kw=7.0,
            charge_efficiency=0.95,
            discharge_efficiency=0.95,
        ),
        forecast_config=ForecastConfig(),
        cheap_window_hours=6.0,
    )
    assert 80.6 <= (plan.maximum_overnight_soc_percent or 0.0) <= 80.8
    assert plan.full_charge_feasible is False
    assert 1.6 <= (plan.additional_cheap_time_to_full_hours or 0.0) <= 1.7
    assert plan.recharge_target_feasible is True
    assert plan.state == "normal"


def test_bad_winter_day_retains_only_energy_needed_before_cheap_window() -> None:
    now = datetime(2026, 12, 1, 18, 0, tzinfo=UTC)
    plan = ForecastPlanningEngine().plan(
        simulation=SimulationState(
            simulated_battery_soc=10.0,
            projected_soc_at_cheap_period_percent=10.0,
        ),
        learned=LearnedState(
            predicted_house_energy_tomorrow_kwh=48.0,
            predicted_house_energy_remaining_today_kwh=None,
        ),
        forecast=SolarForecastState(
            ready=True,
            source="forecast_solar+open_meteo",
            expected_solar_tomorrow_kwh=1.0,
            last_updated=now,
        ),
        simulation_config=SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_initial_percent=10.0,
            battery_reserve_percent=10.0,
            max_charge_kw=7.0,
            charge_efficiency=0.95,
            discharge_efficiency=0.95,
        ),
        forecast_config=ForecastConfig(),
        cheap_window_hours=6.0,
    )
    assert plan.state == "protect"
    assert plan.battery_retention_required is True
    assert (plan.minimum_precheap_soc_percent or 0.0) > 10.0
    assert plan.recharge_target_feasible is False
    assert (plan.recharge_shortfall_kwh or 0.0) > 0.0


def test_hourly_shape_protects_against_sun_arriving_too_late() -> None:
    now = datetime(2026, 12, 1, 18, 0, tzinfo=UTC)
    tomorrow = datetime(2026, 12, 2, 0, 0, tzinfo=UTC)
    # 24kWh house demand is concentrated before midday; the same 24kWh of
    # solar arrives later. Daily totals alone look balanced, but the battery
    # must survive the morning before that solar exists.
    house = tuple([2.0] * 12 + [0.0] * 12)
    solar = [0.0] * 12 + [2.0] * 12
    plan = ForecastPlanningEngine().plan(
        simulation=SimulationState(
            simulated_battery_soc=30.0,
            projected_soc_at_cheap_period_percent=30.0,
        ),
        learned=LearnedState(
            predicted_house_energy_tomorrow_kwh=24.0,
            predicted_house_tomorrow_hourly_kwh=house,
        ),
        forecast=SolarForecastState(
            ready=True,
            source="forecast_solar+open_meteo",
            expected_solar_tomorrow_kwh=24.0,
            hourly=_hourly_solar(tomorrow, solar),
            last_updated=now,
        ),
        simulation_config=SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_reserve_percent=10.0,
            max_charge_kw=7.0,
            charge_efficiency=0.95,
            discharge_efficiency=0.95,
        ),
        forecast_config=ForecastConfig(reserve_safety_margin_percent=5.0),
        cheap_window_hours=6.0,
    )
    assert (plan.required_morning_soc_percent or 0.0) > 50.0
    assert (plan.projected_minimum_soc_tomorrow_percent or 100.0) >= 10.0


def test_same_day_solar_recovery_only_triggers_for_real_energy_deficit() -> None:
    now = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)
    plan = ForecastPlanningEngine().plan(
        simulation=SimulationState(
            simulated_battery_soc=20.0,
            projected_soc_at_cheap_period_percent=20.0,
        ),
        learned=LearnedState(
            predicted_house_energy_tomorrow_kwh=15.0,
            predicted_house_energy_remaining_today_kwh=20.0,
        ),
        forecast=SolarForecastState(
            ready=True,
            source="forecast_solar+open_meteo",
            expected_solar_remaining_today_kwh=5.0,
            expected_solar_tomorrow_kwh=12.0,
            last_updated=now,
        ),
        simulation_config=SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_reserve_percent=10.0,
            max_charge_kw=7.0,
            charge_efficiency=0.95,
            discharge_efficiency=0.95,
        ),
        forecast_config=ForecastConfig(recovery_margin_kwh=1.0),
        cheap_window_hours=6.0,
    )
    assert plan.state == "recovery"
    assert plan.solar_recovery_required is True
    assert (plan.solar_recovery_target_percent or 0.0) > 20.0
