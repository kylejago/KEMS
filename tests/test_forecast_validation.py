"""Tests for Full KEMS Forecast-vs-actual validation."""

from datetime import UTC, date, datetime, timedelta

from kems_core import ForecastObservation, ForecastValidationEngine, Snapshot


def _completed_day(
    target: date,
    *,
    solar_kw: float = 1.0,
    house_kw: float = 2.0,
    grid_import_kw: float = 0.0,
) -> list[Snapshot]:
    start = datetime(target.year, target.month, target.day, tzinfo=UTC)
    return [
        Snapshot(
            timestamp=start + timedelta(minutes=15 * index),
            solar_power_kw=solar_kw,
            house_load_kw=house_kw,
            grid_import_kw=grid_import_kw,
            battery_soc=60.0 - index * 0.1,
            off_peak=False,
        )
        for index in range(96)
    ]


def _observation(
    target: date,
    *,
    forecast_solar: float,
    open_meteo: float,
    fused: float,
    house: float = 48.0,
) -> ForecastObservation:
    captured = datetime(
        target.year,
        target.month,
        target.day,
        tzinfo=UTC,
    ) - timedelta(hours=1)
    return ForecastObservation(
        captured_at=captured,
        target_date=target,
        forecast_solar_kwh=forecast_solar,
        open_meteo_kwh=open_meteo,
        fused_solar_kwh=fused,
        house_kwh=house,
        protection_state="normal",
        required_morning_soc_percent=45.0,
        confidence_percent=80.0,
    )


def test_validation_ranks_sources_and_suggests_evidence_based_correction() -> None:
    start = date(2026, 8, 10)
    records: list[Snapshot] = []
    forecasts: list[ForecastObservation] = []
    for offset in range(3):
        target = start + timedelta(days=offset)
        records.extend(_completed_day(target))
        forecasts.append(
            _observation(
                target,
                forecast_solar=30.0,
                open_meteo=24.0,
                fused=25.0,
            )
        )

    state = ForecastValidationEngine().analyse(
        records,
        forecasts,
        datetime(2026, 8, 13, 12, tzinfo=UTC),
    )

    assert state.ready is True
    assert state.days_validated == 3
    assert state.solar_days_validated == 3
    assert state.house_days_validated == 3
    assert state.best_solar_source == "open_meteo"
    assert state.open_meteo_mae_kwh == 0.25
    assert state.fused_solar_mae_kwh == 1.25
    assert state.forecast_solar_mae_kwh == 6.25
    assert state.house_mae_kwh == 0.5
    assert state.suggested_fused_correction_factor == 0.95
    assert state.latest is not None
    assert state.latest.actual_solar_kwh == 23.75
    assert state.latest.actual_house_kwh == 47.5


def test_validation_rejects_incomplete_days_instead_of_learning_bad_bias() -> None:
    target = date(2026, 8, 10)
    records = _completed_day(target)[:12]
    forecast = _observation(
        target,
        forecast_solar=20.0,
        open_meteo=20.0,
        fused=20.0,
    )

    state = ForecastValidationEngine().analyse(
        records,
        [forecast],
        datetime(2026, 8, 11, 12, tzinfo=UTC),
    )

    assert state.ready is False
    assert state.status == "learning"
    assert state.days_validated == 0
    assert state.fused_solar_mae_kwh is None
    assert state.suggested_fused_correction_factor is None


def test_validation_reports_signed_bias_and_day_rate_import() -> None:
    target = date(2026, 8, 10)
    records = _completed_day(target, solar_kw=1.0, grid_import_kw=0.5)
    forecast = _observation(
        target,
        forecast_solar=28.0,
        open_meteo=26.0,
        fused=27.0,
    )

    state = ForecastValidationEngine().analyse(
        records,
        [forecast],
        datetime(2026, 8, 11, 12, tzinfo=UTC),
    )

    assert state.ready is False
    assert state.fused_solar_bias_kwh == 3.25
    assert state.latest is not None
    assert state.latest.actual_grid_import_kwh == 11.875
    assert state.latest.actual_day_rate_import_kwh == 11.875
    assert state.latest.actual_min_battery_soc_percent == 50.5
