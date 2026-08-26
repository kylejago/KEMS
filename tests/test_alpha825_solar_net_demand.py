"""Regression coverage for Alpha8.25 solar-aware rolling planning."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from kems_core import ForecastHour, ForecastPlanState, LearnedState, SolarForecastState
from kems_core.solar_net_demand import (
    project_solar_net_house_demand,
    route_idle_solar_first,
)

ROOT = Path(__file__).parents[1]


def _forecast(
    now: datetime,
    *,
    confidence: float = 90.0,
    solar_hours: tuple[tuple[int, float], ...] = (
        (2, 2.0),
        (3, 2.0),
        (4, 2.0),
        (5, 2.0),
    ),
) -> SolarForecastState:
    return SolarForecastState(
        ready=True,
        source="forecast_solar+open_meteo",
        confidence_percent=confidence,
        hourly=tuple(
            ForecastHour(
                timestamp=now + timedelta(hours=offset),
                solar_energy_kwh=energy,
            )
            for offset, energy in solar_hours
        ),
    )


def test_high_confidence_hourly_solar_reduces_only_overlapping_house_protection() -> (
    None
):
    now = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    deadline = datetime(2026, 8, 26, 22, 30, tzinfo=UTC)
    result = project_solar_net_house_demand(
        now=now,
        deadline=deadline,
        gross_house_kwh=18.0,
        forecast=_forecast(now),
        forecast_plan=ForecastPlanState(
            ready=True,
            confidence_percent=90.0,
            expected_house_remaining_today_kwh=18.0,
        ),
        learned=LearnedState(typical_house_load_kw=1.0),
    )

    assert result.active is True
    assert 0.0 < result.solar_to_house_credit_kwh < 8.0
    assert result.net_house_kwh == round(
        18.0 - result.solar_to_house_credit_kwh,
        3,
    )
    assert result.net_house_kwh >= 1.8
    assert result.confidence_percent == 90.0


def test_solar_after_deadline_is_not_credited_against_house_reserve() -> None:
    now = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    deadline = datetime(2026, 8, 26, 22, 30, tzinfo=UTC)
    result = project_solar_net_house_demand(
        now=now,
        deadline=deadline,
        gross_house_kwh=18.0,
        forecast=_forecast(now, solar_hours=((16, 20.0),)),
        forecast_plan=ForecastPlanState(ready=True, confidence_percent=90.0),
        learned=LearnedState(typical_house_load_kw=1.0),
    )

    assert result.active is False
    assert result.solar_to_house_credit_kwh == 0.0
    assert result.net_house_kwh == 18.0


def test_low_confidence_forecast_preserves_legacy_gross_house_protection() -> None:
    now = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    result = project_solar_net_house_demand(
        now=now,
        deadline=datetime(2026, 8, 26, 22, 30, tzinfo=UTC),
        gross_house_kwh=17.505,
        forecast=_forecast(now, confidence=60.0),
        forecast_plan=ForecastPlanState(ready=True, confidence_percent=60.0),
        learned=LearnedState(typical_house_load_kw=1.2),
    )

    assert result.active is False
    assert result.net_house_kwh == 17.505
    assert result.solar_to_house_credit_kwh == 0.0


def test_solar_credit_never_removes_more_than_ninety_percent_of_house_reserve() -> None:
    now = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
    result = project_solar_net_house_demand(
        now=now,
        deadline=datetime(2026, 8, 26, 22, 30, tzinfo=UTC),
        gross_house_kwh=10.0,
        forecast=_forecast(
            now,
            confidence=100.0,
            solar_hours=tuple((hour, 50.0) for hour in range(1, 12)),
        ),
        forecast_plan=ForecastPlanState(ready=True, confidence_percent=100.0),
        learned=LearnedState(typical_house_load_kw=2.0),
    )

    assert result.solar_to_house_credit_kwh <= 9.0
    assert result.net_house_kwh >= 1.0


def test_idle_solar_first_routing_eliminates_import_while_exporting_same_solar() -> (
    None
):
    routing = route_idle_solar_first(
        house_kw=1.003,
        solar_kw=1.035,
        requested_solar_to_battery_kw=0.0,
        grid_to_battery_kw=0.0,
        battery_export_kw=0.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        export_allowed=True,
    )

    assert routing.solar_to_home_kw == 1.003
    assert routing.grid_import_kw == 0.0
    assert routing.solar_export_kw == 0.032
    assert routing.grid_export_kw == 0.032


def test_idle_solar_first_preserves_planned_solar_charge_after_house() -> None:
    routing = route_idle_solar_first(
        house_kw=1.0,
        solar_kw=3.0,
        requested_solar_to_battery_kw=1.0,
        grid_to_battery_kw=0.0,
        battery_export_kw=0.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        export_allowed=True,
    )

    assert routing.solar_to_home_kw == 1.0
    assert routing.solar_to_battery_kw == 1.0
    assert routing.solar_export_kw == 1.0
    assert routing.grid_import_kw == 0.0


def test_runtime_installs_solar_net_demand_after_existing_reconciliation_chain() -> (
    None
):
    compat = (ROOT / "custom_components/kems/agile_alpha7_compat.py").read_text()
    runtime = (ROOT / "custom_components/kems/agile_solar_net_demand.py").read_text()

    assert compat.index("install_runtime_reconciliation") < compat.index(
        "install_solar_net_demand"
    )
    assert "rolling._predicted_house_until_deadline" in runtime
    assert "current_runtime._snapshot = _snapshot_with_idle_solar_first" in runtime
    assert '"hardware_writes": "blocked"' in runtime
