"""Persistent day-ahead forecast evidence for Full KEMS Forecast validation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE
from .kems_core import (
    ForecastObservation,
    ForecastPlanState,
    ForecastValidationEngine,
    ForecastValidationState,
    LearnedState,
    Snapshot,
    SolarForecastState,
)

STORAGE_VERSION = 1
CAPTURE_INTERVAL = timedelta(minutes=15)
RETENTION_DAYS = 60


class ForecastValidationRecorder:
    """Persist one rolling day-ahead forecast per target date and validate it."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.forecast_validation",
        )
        self._forecasts: list[ForecastObservation] = []
        self._engine = ForecastValidationEngine()
        self._state = ForecastValidationState()
        self._dirty = False

    @property
    def forecasts(self) -> list[ForecastObservation]:
        """Return retained forecast observations."""
        return list(self._forecasts)

    @property
    def state(self) -> ForecastValidationState:
        """Return the latest calculated validation state."""
        return self._state

    async def async_load(self) -> None:
        """Load persisted day-ahead forecasts."""
        data = await self._store.async_load()
        if not data:
            self._forecasts = []
            return
        forecasts: list[ForecastObservation] = []
        for item in data.get("forecasts", []):
            try:
                forecasts.append(ForecastObservation.from_dict(item))
            except (TypeError, ValueError):
                continue
        self._forecasts = sorted(forecasts, key=lambda item: item.captured_at)
        self._prune(self._forecasts[-1].captured_at if self._forecasts else None)

    async def async_capture(
        self,
        now,
        forecast: SolarForecastState,
        plan: ForecastPlanState,
        learned: LearnedState,
    ) -> bool:
        """Capture the latest pre-midnight view of tomorrow without write spam."""
        if (
            forecast.forecast_solar_tomorrow_kwh is None
            and forecast.open_meteo_tomorrow_kwh is None
            and forecast.expected_solar_tomorrow_kwh is None
            and learned.predicted_house_energy_tomorrow_kwh is None
        ):
            return False

        target_date = now.date() + timedelta(days=1)
        existing = next(
            (
                item
                for item in reversed(self._forecasts)
                if item.target_date == target_date
            ),
            None,
        )
        if existing is not None and now - existing.captured_at < CAPTURE_INTERVAL:
            return False

        observation = ForecastObservation(
            captured_at=now,
            target_date=target_date,
            forecast_solar_kwh=forecast.forecast_solar_tomorrow_kwh,
            open_meteo_kwh=forecast.open_meteo_tomorrow_kwh,
            fused_solar_kwh=forecast.expected_solar_tomorrow_kwh,
            house_kwh=learned.predicted_house_energy_tomorrow_kwh,
            protection_state=plan.state,
            required_morning_soc_percent=plan.required_morning_soc_percent,
            confidence_percent=forecast.confidence_percent,
        )
        self._forecasts = [
            item for item in self._forecasts if item.target_date != target_date
        ]
        self._forecasts.append(observation)
        self._forecasts.sort(key=lambda item: item.captured_at)
        self._prune(now)
        self._dirty = True
        return True

    def analyse(self, records: list[Snapshot], now) -> ForecastValidationState:
        """Recalculate forecast accuracy from retained history."""
        self._state = self._engine.analyse(records, self._forecasts, now)
        return self._state

    async def async_save(self) -> None:
        """Persist captured forecasts when they changed."""
        if not self._dirty:
            return
        await self._store.async_save(
            {"forecasts": [item.to_dict() for item in self._forecasts]}
        )
        self._dirty = False

    def _prune(self, now) -> None:
        """Discard stale target days beyond the validation horizon."""
        if now is None:
            return
        cutoff = now.date() - timedelta(days=RETENTION_DAYS)
        retained = [item for item in self._forecasts if item.target_date >= cutoff]
        if len(retained) != len(self._forecasts):
            self._dirty = True
        self._forecasts = retained
