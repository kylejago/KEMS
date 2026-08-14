"""Home Assistant forecast sources for Full KEMS Forecast."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .kems_core import (
    FOXHOLE_PROPOSAL_PROFILE,
    ForecastConfig,
    ForecastHour,
    SolarForecastState,
    fuse_solar_forecasts,
)

LOGGER = logging.getLogger(__name__)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


@dataclass(frozen=True, slots=True)
class _OpenMeteoResult:
    remaining_today_kwh: float | None = None
    tomorrow_kwh: float | None = None
    hourly: tuple[ForecastHour, ...] = ()
    cloud_tomorrow_percent: float | None = None
    precipitation_tomorrow_mm: float | None = None
    fetched_at: datetime | None = None
    error: str | None = None


class SolarForecastCoordinator:
    """Read Forecast.Solar and independently check it with Open-Meteo."""

    def __init__(self, hass: HomeAssistant, config: ForecastConfig) -> None:
        self.hass = hass
        self.config = config
        self._open_meteo_cache = _OpenMeteoResult()

    async def async_update(self, now: datetime) -> SolarForecastState:
        """Return the latest fused forecast without making KEMS depend on it."""
        if not self.config.enabled:
            return SolarForecastState(
                ready=False,
                source="disabled",
                last_updated=now,
                error="Full KEMS Forecast is disabled in settings",
            )
        fs_remaining, fs_tomorrow, fs_count = self._read_forecast_solar()
        open_meteo = await self._async_open_meteo(now)
        return fuse_solar_forecasts(
            now=now,
            forecast_solar_remaining_today_kwh=fs_remaining,
            forecast_solar_tomorrow_kwh=fs_tomorrow,
            forecast_solar_entity_count=fs_count,
            open_meteo_remaining_today_kwh=open_meteo.remaining_today_kwh,
            open_meteo_tomorrow_kwh=open_meteo.tomorrow_kwh,
            hourly=open_meteo.hourly,
            average_cloud_cover_tomorrow_percent=open_meteo.cloud_tomorrow_percent,
            precipitation_tomorrow_mm=open_meteo.precipitation_tomorrow_mm,
            error=open_meteo.error,
        )

    def _read_forecast_solar(self) -> tuple[float | None, float | None, int]:
        """Auto-discover Forecast.Solar energy sensors from the entity registry."""
        registry = er.async_get(self.hass)
        remaining_values: list[float] = []
        tomorrow_values: list[float] = []
        matched_entries: set[str] = set()

        for entry in registry.entities.values():
            if getattr(entry, "platform", None) != "forecast_solar":
                continue
            entity_id = getattr(entry, "entity_id", "")
            if not str(entity_id).startswith("sensor."):
                continue
            state = self.hass.states.get(entity_id)
            if state is None or state.state in {"unknown", "unavailable", "none", ""}:
                continue
            try:
                value = float(state.state)
            except (TypeError, ValueError):
                continue
            unit = str(state.attributes.get("unit_of_measurement", "")).lower()
            if unit == "wh":
                value /= 1000.0
            elif unit not in {"kwh", "kw h", ""}:
                continue

            identity = " ".join(
                str(item or "").lower()
                for item in (
                    getattr(entry, "unique_id", ""),
                    getattr(entry, "original_name", ""),
                    state.attributes.get("friendly_name", ""),
                    entity_id,
                )
            )
            if (
                "energy_production_today_remaining" in identity
                or "remaining today" in identity
            ):
                remaining_values.append(max(value, 0.0))
                matched_entries.add(str(entity_id))
            elif (
                "energy_production_tomorrow" in identity
                or "production - tomorrow" in identity
            ):
                tomorrow_values.append(max(value, 0.0))
                matched_entries.add(str(entity_id))

        return (
            round(sum(remaining_values), 3) if remaining_values else None,
            round(sum(tomorrow_values), 3) if tomorrow_values else None,
            len(matched_entries),
        )

    async def _async_open_meteo(self, now: datetime) -> _OpenMeteoResult:
        """Fetch multi-array hourly GTI, cached to keep API usage tiny."""
        if not self.config.open_meteo_enabled:
            return _OpenMeteoResult(error="Open-Meteo disabled")

        cached_at = self._open_meteo_cache.fetched_at
        if cached_at is not None and now - cached_at < timedelta(
            minutes=max(self.config.open_meteo_refresh_minutes, 15)
        ):
            return self._open_meteo_cache

        try:
            result = await self._async_fetch_open_meteo(now)
        except Exception as err:  # network errors must never break KEMS
            LOGGER.warning("Open-Meteo forecast update failed: %s", err)
            if self._open_meteo_cache.fetched_at is not None:
                return _OpenMeteoResult(
                    remaining_today_kwh=self._open_meteo_cache.remaining_today_kwh,
                    tomorrow_kwh=self._open_meteo_cache.tomorrow_kwh,
                    hourly=self._open_meteo_cache.hourly,
                    cloud_tomorrow_percent=(
                        self._open_meteo_cache.cloud_tomorrow_percent
                    ),
                    precipitation_tomorrow_mm=(
                        self._open_meteo_cache.precipitation_tomorrow_mm
                    ),
                    fetched_at=self._open_meteo_cache.fetched_at,
                    error=f"Using cached Open-Meteo data after update error: {err}",
                )
            return _OpenMeteoResult(error=str(err))

        self._open_meteo_cache = result
        return result

    async def _async_fetch_open_meteo(self, now: datetime) -> _OpenMeteoResult:
        session = async_get_clientsession(self.hass)
        timezone_name = str(self.hass.config.time_zone)
        latitude = float(self.hass.config.latitude)
        longitude = float(self.hass.config.longitude)

        async def fetch_array(tilt: int, azimuth_ha: int) -> dict[str, Any]:
            # Home Assistant / Forecast.Solar: 0=N, 90=E, 180=S, 270=W.
            # Open-Meteo: 0=S, -90=E, +90=W, +/-180=N.
            open_meteo_azimuth = (float(azimuth_ha) % 360.0) - 180.0
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "hourly": "global_tilted_irradiance,cloud_cover,precipitation",
                "tilt": float(tilt),
                "azimuth": open_meteo_azimuth,
                "models": "ukmo_seamless",
                "timezone": timezone_name,
                "forecast_days": 3,
            }
            timeout = ClientTimeout(total=20)
            async with session.get(
                OPEN_METEO_URL, params=params, timeout=timeout
            ) as response:
                response.raise_for_status()
                payload = await response.json()
                if payload.get("error"):
                    raise RuntimeError(str(payload.get("reason") or "Open-Meteo error"))
                return payload

        payloads = await asyncio.gather(
            *(
                fetch_array(array.tilt_degrees, array.azimuth_degrees)
                for array in FOXHOLE_PROPOSAL_PROFILE.arrays
            )
        )
        first = payloads[0]
        times = list(first.get("hourly", {}).get("time", []))
        if not times:
            raise RuntimeError("Open-Meteo returned no hourly timestamps")

        tz = ZoneInfo(timezone_name)
        gti_by_array = [
            list(payload.get("hourly", {}).get("global_tilted_irradiance", []))
            for payload in payloads
        ]
        cloud_values = list(first.get("hourly", {}).get("cloud_cover", []))
        precipitation_values = list(first.get("hourly", {}).get("precipitation", []))
        arrays = FOXHOLE_PROPOSAL_PROFILE.arrays
        performance = max(self.config.performance_ratio, 0.0)
        shading = max(FOXHOLE_PROPOSAL_PROFILE.shading_factor, 0.0)
        inverter_limit = max(FOXHOLE_PROPOSAL_PROFILE.inverter_limit_kw, 0.0)

        hourly_points: list[ForecastHour] = []
        for index, raw_time in enumerate(times):
            timestamp = datetime.fromisoformat(str(raw_time))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=tz)
            array_power_kw = 0.0
            for array_index, array in enumerate(arrays):
                values = gti_by_array[array_index]
                gti = values[index] if index < len(values) else None
                if gti is None:
                    continue
                array_power_kw += (
                    max(float(gti), 0.0)
                    / 1000.0
                    * array.capacity_kwp
                    * performance
                    * shading
                )
            energy_kwh = min(array_power_kw, inverter_limit)
            cloud = cloud_values[index] if index < len(cloud_values) else None
            precipitation = (
                precipitation_values[index]
                if index < len(precipitation_values)
                else None
            )
            hourly_points.append(
                ForecastHour(
                    timestamp=timestamp,
                    solar_energy_kwh=round(energy_kwh, 3),
                    cloud_cover_percent=(float(cloud) if cloud is not None else None),
                    precipitation_mm=(
                        float(precipitation) if precipitation is not None else None
                    ),
                )
            )

        tomorrow = now.date() + timedelta(days=1)
        remaining_today = sum(
            point.solar_energy_kwh
            for point in hourly_points
            if point.timestamp.date() == now.date() and point.timestamp > now
        )
        tomorrow_points = [
            point for point in hourly_points if point.timestamp.date() == tomorrow
        ]
        tomorrow_energy = sum(point.solar_energy_kwh for point in tomorrow_points)
        clouds = [
            point.cloud_cover_percent
            for point in tomorrow_points
            if point.cloud_cover_percent is not None
        ]
        precipitation = sum(point.precipitation_mm or 0.0 for point in tomorrow_points)

        return _OpenMeteoResult(
            remaining_today_kwh=round(remaining_today, 3),
            tomorrow_kwh=round(tomorrow_energy, 3),
            hourly=tuple(hourly_points),
            cloud_tomorrow_percent=(
                round(sum(clouds) / len(clouds), 1) if clouds else None
            ),
            precipitation_tomorrow_mm=round(precipitation, 2),
            fetched_at=now,
        )
