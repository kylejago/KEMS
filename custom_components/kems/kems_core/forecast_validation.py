"""Forecast-vs-actual validation for Full KEMS Forecast."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from statistics import fmean

from .models import Snapshot

MAX_SAMPLE_GAP_MINUTES = 15.0
MIN_DAY_COVERAGE_PERCENT = 75.0
MIN_READY_DAYS = 3
TARGET_CONFIDENCE_DAYS = 14


@dataclass(frozen=True, slots=True)
class ForecastObservation:
    """One persisted day-ahead forecast captured before its target day."""

    captured_at: datetime
    target_date: date
    forecast_solar_kwh: float | None = None
    open_meteo_kwh: float | None = None
    fused_solar_kwh: float | None = None
    house_kwh: float | None = None
    protection_state: str | None = None
    required_morning_soc_percent: float | None = None
    confidence_percent: float | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        data = asdict(self)
        data["captured_at"] = self.captured_at.isoformat()
        data["target_date"] = self.target_date.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ForecastObservation:
        """Restore a persisted forecast observation."""
        values = dict(data)
        captured_at = values.get("captured_at")
        target_date = values.get("target_date")
        if isinstance(captured_at, str):
            values["captured_at"] = datetime.fromisoformat(captured_at)
        if isinstance(target_date, str):
            values["target_date"] = date.fromisoformat(target_date)
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ForecastValidationDay:
    """Forecast and actual energy comparison for one completed local day."""

    date: date
    samples: int = 0
    solar_coverage_percent: float = 0.0
    house_coverage_percent: float = 0.0
    grid_coverage_percent: float = 0.0
    actual_solar_kwh: float | None = None
    actual_house_kwh: float | None = None
    actual_grid_import_kwh: float | None = None
    actual_day_rate_import_kwh: float | None = None
    actual_min_battery_soc_percent: float | None = None
    forecast_solar_kwh: float | None = None
    open_meteo_kwh: float | None = None
    fused_solar_kwh: float | None = None
    house_forecast_kwh: float | None = None
    forecast_solar_error_kwh: float | None = None
    open_meteo_error_kwh: float | None = None
    fused_solar_error_kwh: float | None = None
    house_error_kwh: float | None = None
    protection_state: str | None = None
    required_morning_soc_percent: float | None = None
    forecast_confidence_percent: float | None = None

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible validation details."""
        data = asdict(self)
        data["date"] = self.date.isoformat()
        return data


@dataclass(frozen=True, slots=True)
class ForecastValidationState:
    """Rolling forecast accuracy and evidence-based correction guidance."""

    ready: bool = False
    status: str = "unavailable"
    days_validated: int = 0
    solar_days_validated: int = 0
    house_days_validated: int = 0
    confidence_percent: float = 0.0
    best_solar_source: str = "unavailable"
    forecast_solar_mae_kwh: float | None = None
    forecast_solar_bias_kwh: float | None = None
    forecast_solar_mape_percent: float | None = None
    open_meteo_mae_kwh: float | None = None
    open_meteo_bias_kwh: float | None = None
    open_meteo_mape_percent: float | None = None
    fused_solar_mae_kwh: float | None = None
    fused_solar_bias_kwh: float | None = None
    fused_solar_mape_percent: float | None = None
    house_mae_kwh: float | None = None
    house_bias_kwh: float | None = None
    house_mape_percent: float | None = None
    suggested_fused_correction_factor: float | None = None
    latest: ForecastValidationDay | None = None
    days: tuple[ForecastValidationDay, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible validation diagnostics."""
        data = asdict(self)
        data["latest"] = self.latest.to_dict() if self.latest is not None else None
        data["days"] = [item.to_dict() for item in self.days]
        return data


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(float(value), digits)


def _error(predicted: float | None, actual: float | None) -> float | None:
    if predicted is None or actual is None:
        return None
    return round(float(predicted) - float(actual), 3)


def _metric(
    days: list[ForecastValidationDay],
    forecast_attribute: str,
    actual_attribute: str,
) -> tuple[int, float | None, float | None, float | None]:
    pairs: list[tuple[float, float]] = []
    for item in days:
        predicted = getattr(item, forecast_attribute)
        actual = getattr(item, actual_attribute)
        if predicted is None or actual is None:
            continue
        pairs.append((float(predicted), float(actual)))
    if not pairs:
        return 0, None, None, None
    errors = [predicted - actual for predicted, actual in pairs]
    percentages = [
        abs(predicted - actual) / actual * 100.0
        for predicted, actual in pairs
        if actual >= 0.5
    ]
    return (
        len(pairs),
        round(fmean(abs(value) for value in errors), 3),
        round(fmean(errors), 3),
        round(fmean(percentages), 1) if percentages else None,
    )


class ForecastValidationEngine:
    """Compare retained day-ahead forecasts with completed observed days."""

    def analyse(
        self,
        records: list[Snapshot],
        forecasts: list[ForecastObservation],
        now: datetime,
    ) -> ForecastValidationState:
        """Return rolling provider, fused-solar and house forecast accuracy."""
        if not forecasts:
            return ForecastValidationState()

        latest_by_date: dict[date, ForecastObservation] = {}
        for forecast in forecasts:
            if forecast.target_date >= now.date():
                continue
            existing = latest_by_date.get(forecast.target_date)
            if existing is None or forecast.captured_at > existing.captured_at:
                latest_by_date[forecast.target_date] = forecast

        records_by_date: dict[date, list[Snapshot]] = {}
        for record in records:
            if record.timestamp.date() >= now.date():
                continue
            records_by_date.setdefault(record.timestamp.date(), []).append(record)

        days: list[ForecastValidationDay] = []
        for target_date, forecast in sorted(latest_by_date.items()):
            day_records = sorted(
                records_by_date.get(target_date, []),
                key=lambda item: item.timestamp,
            )
            if len(day_records) < 2:
                continue
            item = self._validate_day(target_date, day_records, forecast)
            if (
                item.solar_coverage_percent >= MIN_DAY_COVERAGE_PERCENT
                or item.house_coverage_percent >= MIN_DAY_COVERAGE_PERCENT
            ):
                days.append(item)

        if not days:
            return ForecastValidationState(status="learning")

        fs_count, fs_mae, fs_bias, fs_mape = _metric(
            days, "forecast_solar_kwh", "actual_solar_kwh"
        )
        om_count, om_mae, om_bias, om_mape = _metric(
            days, "open_meteo_kwh", "actual_solar_kwh"
        )
        fused_count, fused_mae, fused_bias, fused_mape = _metric(
            days, "fused_solar_kwh", "actual_solar_kwh"
        )
        house_count, house_mae, house_bias, house_mape = _metric(
            days, "house_forecast_kwh", "actual_house_kwh"
        )

        source_mae = {
            source: mae
            for source, mae in (
                ("forecast_solar", fs_mae),
                ("open_meteo", om_mae),
                ("fused", fused_mae),
            )
            if mae is not None
        }
        best_source = (
            min(source_mae, key=source_mae.get) if source_mae else "unavailable"
        )

        fused_pairs = [
            (float(item.fused_solar_kwh), float(item.actual_solar_kwh))
            for item in days
            if item.fused_solar_kwh is not None and item.actual_solar_kwh is not None
        ]
        correction: float | None = None
        if len(fused_pairs) >= MIN_READY_DAYS:
            forecast_total = sum(predicted for predicted, _ in fused_pairs)
            actual_total = sum(actual for _, actual in fused_pairs)
            if forecast_total >= 1.0:
                correction = round(
                    min(max(actual_total / forecast_total, 0.70), 1.30),
                    3,
                )

        evidence_days = max(fused_count, fs_count, om_count, house_count)
        ready = evidence_days >= MIN_READY_DAYS
        confidence = round(
            min(evidence_days / TARGET_CONFIDENCE_DAYS, 1.0) * 100.0,
            1,
        )
        retained = tuple(days[-30:])
        return ForecastValidationState(
            ready=ready,
            status="ready" if ready else "learning",
            days_validated=len(days),
            solar_days_validated=max(fs_count, om_count, fused_count),
            house_days_validated=house_count,
            confidence_percent=confidence,
            best_solar_source=best_source,
            forecast_solar_mae_kwh=fs_mae,
            forecast_solar_bias_kwh=fs_bias,
            forecast_solar_mape_percent=fs_mape,
            open_meteo_mae_kwh=om_mae,
            open_meteo_bias_kwh=om_bias,
            open_meteo_mape_percent=om_mape,
            fused_solar_mae_kwh=fused_mae,
            fused_solar_bias_kwh=fused_bias,
            fused_solar_mape_percent=fused_mape,
            house_mae_kwh=house_mae,
            house_bias_kwh=house_bias,
            house_mape_percent=house_mape,
            suggested_fused_correction_factor=correction,
            latest=retained[-1] if retained else None,
            days=retained,
        )

    def _validate_day(
        self,
        target_date: date,
        records: list[Snapshot],
        forecast: ForecastObservation,
    ) -> ForecastValidationDay:
        solar_kwh = 0.0
        house_kwh = 0.0
        grid_import_kwh = 0.0
        day_rate_import_kwh = 0.0
        solar_minutes = 0.0
        house_minutes = 0.0
        grid_minutes = 0.0

        for current, following in zip(records, records[1:], strict=False):
            seconds = (following.timestamp - current.timestamp).total_seconds()
            if seconds <= 0:
                continue
            minutes = min(seconds / 60.0, MAX_SAMPLE_GAP_MINUTES)
            hours = minutes / 60.0
            if current.solar_power_kw is not None:
                solar_kwh += max(float(current.solar_power_kw), 0.0) * hours
                solar_minutes += minutes
            if current.house_load_kw is not None:
                house_kwh += max(float(current.house_load_kw), 0.0) * hours
                house_minutes += minutes
            if current.grid_import_kw is not None:
                imported = max(float(current.grid_import_kw), 0.0) * hours
                grid_import_kwh += imported
                grid_minutes += minutes
                if not current.cheap_period_confirmed:
                    day_rate_import_kwh += imported

        solar_coverage = min(solar_minutes / (24 * 60) * 100.0, 100.0)
        house_coverage = min(house_minutes / (24 * 60) * 100.0, 100.0)
        grid_coverage = min(grid_minutes / (24 * 60) * 100.0, 100.0)
        actual_solar = (
            round(solar_kwh, 3)
            if solar_coverage >= MIN_DAY_COVERAGE_PERCENT
            else None
        )
        actual_house = (
            round(house_kwh, 3)
            if house_coverage >= MIN_DAY_COVERAGE_PERCENT
            else None
        )
        battery_values = [
            float(item.battery_soc)
            for item in records
            if item.battery_soc is not None
        ]

        return ForecastValidationDay(
            date=target_date,
            samples=len(records),
            solar_coverage_percent=round(solar_coverage, 1),
            house_coverage_percent=round(house_coverage, 1),
            grid_coverage_percent=round(grid_coverage, 1),
            actual_solar_kwh=actual_solar,
            actual_house_kwh=actual_house,
            actual_grid_import_kwh=(
                round(grid_import_kwh, 3)
                if grid_coverage >= MIN_DAY_COVERAGE_PERCENT
                else None
            ),
            actual_day_rate_import_kwh=(
                round(day_rate_import_kwh, 3)
                if grid_coverage >= MIN_DAY_COVERAGE_PERCENT
                else None
            ),
            actual_min_battery_soc_percent=(
                round(min(battery_values), 1) if battery_values else None
            ),
            forecast_solar_kwh=_round(forecast.forecast_solar_kwh),
            open_meteo_kwh=_round(forecast.open_meteo_kwh),
            fused_solar_kwh=_round(forecast.fused_solar_kwh),
            house_forecast_kwh=_round(forecast.house_kwh),
            forecast_solar_error_kwh=_error(forecast.forecast_solar_kwh, actual_solar),
            open_meteo_error_kwh=_error(forecast.open_meteo_kwh, actual_solar),
            fused_solar_error_kwh=_error(forecast.fused_solar_kwh, actual_solar),
            house_error_kwh=_error(forecast.house_kwh, actual_house),
            protection_state=forecast.protection_state,
            required_morning_soc_percent=_round(
                forecast.required_morning_soc_percent, 1
            ),
            forecast_confidence_percent=_round(forecast.confidence_percent, 1),
        )
