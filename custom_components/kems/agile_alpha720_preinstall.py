"""Alpha 7.20 pre-install historical evidence reconstruction.

When the proposed solar system is not yet installed, KEMS can combine retained
Home Assistant whole-house demand statistics with historical Open-Meteo tilted
irradiance for the accepted proposal arrays. The result is explicitly a
hypothetical proposal-system replay, never claimed as actual solar production.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from aiohttp import ClientTimeout
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import agile_history_backfill as backfill
from .const import (
    CONF_FORECAST_OPEN_METEO_ENABLED,
    CONF_FORECAST_PERFORMANCE_RATIO,
    DEFAULT_OPTIONS,
    DOMAIN,
)
from .kems_core import FOXHOLE_PROPOSAL_PROFILE, SimulationConfig, Snapshot
from .tariff import TariffSettings

LOGGER = logging.getLogger(__name__)

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_EVIDENCE_SENSOR = "sensor.kems_preinstall_historical_evidence"
_SOURCE_MAP_SENSOR = "sensor.kems_agile_backfill_source_map"
_ATTRIBUTION = "Historical irradiance by Open-Meteo; proposal PV model by KEMS"


@dataclass(frozen=True, slots=True)
class _EvidenceResult:
    records: tuple[Snapshot, ...] = ()
    state: dict[str, Any] | None = None


def _option(hass, key: str, default: Any) -> Any:
    """Read one KEMS option without coupling the backfill engine to coordinator."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return default
    return entries[0].options.get(key, default)


def _performance_ratio(hass) -> float:
    """Return the same configured PV performance ratio used by live forecasting."""
    raw = _option(
        hass,
        CONF_FORECAST_PERFORMANCE_RATIO,
        DEFAULT_OPTIONS[CONF_FORECAST_PERFORMANCE_RATIO],
    )
    try:
        return min(max(float(raw), 0.1), 1.2)
    except (TypeError, ValueError):
        return 0.85


def _open_meteo_enabled(hass) -> bool:
    raw = _option(
        hass,
        CONF_FORECAST_OPEN_METEO_ENABLED,
        DEFAULT_OPTIONS[CONF_FORECAST_OPEN_METEO_ENABLED],
    )
    return bool(raw)


def _normalise_archive_payloads(
    payloads: list[dict[str, Any]],
    *,
    performance_ratio: float,
    proposal_factor: float,
) -> dict[datetime, float]:
    """Convert per-array historical GTI payloads into hourly proposal PV power."""
    arrays = FOXHOLE_PROPOSAL_PROFILE.arrays
    totals: dict[datetime, float] = {}
    for array, payload in zip(arrays, payloads, strict=True):
        hourly = payload.get("hourly", {}) if isinstance(payload, dict) else {}
        times = list(hourly.get("time", [])) if isinstance(hourly, dict) else []
        values = (
            list(hourly.get("global_tilted_irradiance", []))
            if isinstance(hourly, dict)
            else []
        )
        for index, raw_time in enumerate(times):
            if index >= len(values) or values[index] is None:
                continue
            try:
                timestamp = datetime.fromisoformat(str(raw_time))
                gti = max(float(values[index]), 0.0)
            except (TypeError, ValueError):
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            else:
                timestamp = timestamp.astimezone(UTC)
            power = (
                gti
                / 1000.0
                * array.capacity_kwp
                * max(performance_ratio, 0.0)
                * max(FOXHOLE_PROPOSAL_PROFILE.shading_factor, 0.0)
                * max(proposal_factor, 0.0)
            )
            totals[timestamp] = totals.get(timestamp, 0.0) + power

    inverter_limit = max(FOXHOLE_PROPOSAL_PROFILE.inverter_limit_kw, 0.0)
    return {
        timestamp: round(min(max(power, 0.0), inverter_limit), 3)
        for timestamp, power in totals.items()
    }


async def _async_fetch_proposal_solar(
    hass,
    *,
    start_day: date,
    end_day: date,
    performance_ratio: float,
    proposal_factor: float,
) -> tuple[dict[datetime, float], dict[str, Any]]:
    """Fetch historical GTI for every accepted proposal array."""
    if end_day < start_day:
        return {}, {"available": False, "reason": "no historical days requested"}

    session = async_get_clientsession(hass)
    latitude = float(hass.config.latitude)
    longitude = float(hass.config.longitude)

    async def fetch_array(tilt: int, azimuth_ha: int) -> dict[str, Any]:
        # Home Assistant/Forecast.Solar: 0=N, 90=E, 180=S, 270=W.
        # Open-Meteo tilted irradiance: 0=S, -90=E, +90=W, +/-180=N.
        azimuth = (float(azimuth_ha) % 360.0) - 180.0
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_day.isoformat(),
            "end_date": end_day.isoformat(),
            "hourly": "global_tilted_irradiance",
            "tilt": float(tilt),
            "azimuth": azimuth,
            # UTC/GMT keeps the returned hours aligned with HA statistics,
            # including UK DST transition days.
            "timezone": "GMT",
        }
        async with session.get(
            OPEN_METEO_ARCHIVE_URL,
            params=params,
            timeout=ClientTimeout(total=30),
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
    rows = _normalise_archive_payloads(
        list(payloads),
        performance_ratio=performance_ratio,
        proposal_factor=proposal_factor,
    )
    days = sorted({timestamp.date() for timestamp in rows})
    state = {
        "available": bool(rows),
        "source": "open_meteo_historical_reanalysis",
        "attribution": _ATTRIBUTION,
        "historical_weather_api": True,
        "actual_solar_generation": False,
        "proposal_profile": FOXHOLE_PROPOSAL_PROFILE.name,
        "array_count": len(FOXHOLE_PROPOSAL_PROFILE.arrays),
        "solar_capacity_kwp": FOXHOLE_PROPOSAL_PROFILE.solar_capacity_kwp,
        "inverter_limit_kw": FOXHOLE_PROPOSAL_PROFILE.inverter_limit_kw,
        "performance_ratio": round(performance_ratio, 3),
        "proposal_factor": round(proposal_factor, 3),
        "hourly_rows": len(rows),
        "weather_days": len(days),
        "oldest_weather_day": days[0].isoformat() if days else None,
        "latest_weather_day": days[-1].isoformat() if days else None,
        "fidelity": (
            "historical weather reanalysis applied to the accepted proposal PV "
            "geometry; this is hypothetical production, not measured solar"
        ),
    }
    return rows, state


async def _async_build_evidence(
    self,
    *,
    baseline_records: list[Snapshot],
    now: datetime,
    tariff: TariffSettings,
    config: SimulationConfig,
) -> _EvidenceResult:
    """Build hourly hybrid evidence for days not already covered by KEMS/backfill."""
    if not config.proposal_solar_enabled:
        return _EvidenceResult(
            state={"available": False, "reason": "proposal solar simulation disabled"}
        )
    if not _open_meteo_enabled(self._hass):
        return _EvidenceResult(
            state={"available": False, "reason": "Open-Meteo disabled in KEMS settings"}
        )
    house_entity = self._entities.house_load_kw
    if not house_entity:
        return _EvidenceResult(
            state={
                "available": False,
                "reason": "historical house-load source is not configured",
            }
        )
    if not self._hass.services.has_service("recorder", "get_statistics"):
        return _EvidenceResult(
            state={
                "available": False,
                "reason": "recorder.get_statistics is unavailable",
            }
        )

    local_now = now.astimezone(backfill.LONDON)
    today = local_now.date()
    start_day = today - timedelta(days=backfill.TARGET_DAYS)
    end_day = today - timedelta(days=1)
    covered_days = {
        item.timestamp.astimezone(backfill.LONDON).date()
        for item in baseline_records
        if start_day <= item.timestamp.astimezone(backfill.LONDON).date() <= end_day
    }
    missing_days = {
        start_day + timedelta(days=offset) for offset in range(backfill.TARGET_DAYS)
    } - covered_days
    if not missing_days:
        return _EvidenceResult(
            state={
                "available": False,
                "reason": "existing KEMS/backfill already covers the rolling window",
            }
        )

    sources = {"house_load_kw": house_entity}
    if self._entities.ev_power_kw:
        sources["ev_power_kw"] = self._entities.ev_power_kw
    start = datetime.combine(start_day, time.min, tzinfo=backfill.LONDON).astimezone(
        UTC
    )
    end = datetime.combine(today, time.min, tzinfo=backfill.LONDON).astimezone(UTC)
    try:
        response = await self._hass.services.async_call(
            "recorder",
            "get_statistics",
            {
                "start_time": start,
                "end_time": end,
                "statistic_ids": sorted(set(sources.values())),
                "period": "hour",
                "types": ["mean", "state"],
            },
            blocking=True,
            return_response=True,
        )
    except (HomeAssistantError, TypeError, ValueError) as err:
        return _EvidenceResult(
            state={
                "available": False,
                "reason": f"house-load statistics query failed: {err}",
            }
        )

    statistics = response.get("statistics", {}) if isinstance(response, dict) else {}
    rows = backfill._normalise_statistics(
        statistics,
        source_entities=sources,
        units=self._source_units(sources),
    )
    house_rows = rows.get("house_load_kw", {})
    candidate_days = sorted(
        {
            timestamp.astimezone(backfill.LONDON).date()
            for timestamp in house_rows
            if timestamp.astimezone(backfill.LONDON).date() in missing_days
        }
    )
    if not candidate_days:
        return _EvidenceResult(
            state={
                "available": False,
                "reason": "no uncovered hourly house-load statistics were found",
                "house_entity": house_entity,
            }
        )

    try:
        solar_rows, solar_state = await _async_fetch_proposal_solar(
            self._hass,
            start_day=candidate_days[0],
            end_day=candidate_days[-1],
            performance_ratio=_performance_ratio(self._hass),
            proposal_factor=config.proposal_solar_factor,
        )
    except Exception as err:  # network evidence must never break KEMS
        LOGGER.warning("Historical proposal-solar reconstruction failed: %s", err)
        return _EvidenceResult(
            state={
                "available": False,
                "reason": f"historical irradiance fetch failed: {err}",
                "house_entity": house_entity,
            }
        )
    if not solar_rows:
        return _EvidenceResult(
            state={
                **solar_state,
                "available": False,
                "reason": "Open-Meteo returned no historical tilted irradiance",
                "house_entity": house_entity,
            }
        )

    rows["solar_power_kw"] = solar_rows
    source_presence = {
        "house_load_kw": house_entity,
        "solar_power_kw": "Open-Meteo historical proposal reconstruction",
    }
    if self._entities.ev_power_kw:
        source_presence["ev_power_kw"] = self._entities.ev_power_kw

    records: list[Snapshot] = []
    reconstructed_days: set[date] = set()
    insufficient_days: set[date] = set()
    for day in candidate_days:
        day_records = backfill._build_day(
            day,
            rows=rows,
            tariff=tariff,
            config=config,
            source_entities=source_presence,
        )
        expected = backfill._expected_hours(day)
        minimum = max(int(expected * backfill.MIN_DAY_COVERAGE), 2)
        if len(day_records) - 1 < minimum:
            insufficient_days.add(day)
            continue
        for item in day_records:
            data = item.to_dict()
            data["grid_flow_mode"] = "preinstall_hybrid_reconstruction"
            data["forecast_source"] = "open_meteo_historical_reanalysis"
            data["forecast_confidence_percent"] = 0.0
            records.append(Snapshot.from_dict(data))
        reconstructed_days.add(day)

    state = {
        **solar_state,
        "available": bool(reconstructed_days),
        "house_entity": house_entity,
        "house_statistic_resolution": "hour",
        "reconstructed_days": len(reconstructed_days),
        "insufficient_house_history_days": len(insufficient_days),
        "earliest_reconstructed_day": (
            min(reconstructed_days).isoformat() if reconstructed_days else None
        ),
        "latest_reconstructed_day": (
            max(reconstructed_days).isoformat() if reconstructed_days else None
        ),
        "method": "ha_house_load+open_meteo_proposal_solar",
        "comparison_class": "hypothetical_preinstall_evidence",
    }
    return _EvidenceResult(
        tuple(sorted(records, key=lambda item: item.timestamp)), state
    )


def _overlay_diagnostics(
    self,
    *,
    native_records: list[Snapshot],
    baseline_records: list[Snapshot],
    evidence_records: tuple[Snapshot, ...],
    evidence_state: dict[str, Any],
    now: datetime,
) -> None:
    """Keep native/direct/reconstructed coverage separate and transparent."""
    today = now.astimezone(backfill.LONDON).date()
    start_day = today - timedelta(days=backfill.TARGET_DAYS)

    def days(values) -> set[date]:
        return {
            item.timestamp.astimezone(backfill.LONDON).date()
            for item in values
            if start_day <= item.timestamp.astimezone(backfill.LONDON).date() < today
        }

    native_days = days(native_records)
    baseline_days = days(baseline_records)
    reconstructed_days = days(evidence_records) - baseline_days
    covered_days = baseline_days | reconstructed_days

    if reconstructed_days:
        self._state.update(
            {
                "native_kems_days": len(native_days),
                "proposal_reconstructed_days": len(reconstructed_days),
                "covered_days": len(covered_days),
                "coverage_percent": round(
                    100 * len(covered_days) / backfill.TARGET_DAYS,
                    1,
                ),
                "insufficient_days": max(
                    backfill.TARGET_DAYS - len(covered_days),
                    0,
                ),
                "backfill_method": "ha_house_load+open_meteo_proposal_solar",
                "proposal_solar_reconstruction_used": True,
                "proposal_solar_reconstruction": evidence_state,
                "earliest_backfilled_day": min(reconstructed_days).isoformat(),
                "latest_backfilled_day": max(reconstructed_days).isoformat(),
                "backfill_resolution": (
                    "hourly HA house demand + hourly Open-Meteo historical GTI"
                ),
                "strategy_fidelity": (
                    "native KEMS days remain highest fidelity; reconstructed days "
                    "use measured historical house demand and hypothetical proposal PV"
                ),
                "forecast_fidelity": (
                    "historical weather reanalysis is not a historical forecast and "
                    "is never labelled as measured PV generation"
                ),
                "reason": (
                    "Pre-install evidence recovered from HA whole-house statistics "
                    "plus historical proposal-solar reconstruction"
                ),
            }
        )
        current = self._hass.states.get(backfill.ENTITY_ID)
        attributes = dict(self._state)
        self._hass.states.async_set(
            backfill.ENTITY_ID,
            f"{len(covered_days)}/{backfill.TARGET_DAYS} days",
            attributes,
        )

    source_map = self._hass.states.get(_SOURCE_MAP_SENSOR)
    if source_map is not None:
        attrs = dict(source_map.attributes)
        attrs.update(
            {
                "proposal_solar_reconstruction_ready": bool(reconstructed_days),
                "proposal_reconstructed_days": len(reconstructed_days),
                "hybrid_proposal_path_ready": bool(reconstructed_days),
                "hybrid_proposal_method": evidence_state.get("method"),
                "hybrid_proposal_fidelity": evidence_state.get("fidelity"),
            }
        )
        missing = list(attrs.get("missing_prerequisites") or [])
        if reconstructed_days:
            missing = [item for item in missing if "solar_power_kw" not in str(item)]
        attrs["missing_prerequisites"] = missing
        attrs["replay_path_ready"] = bool(
            attrs.get("direct_path_ready") or attrs.get("hybrid_proposal_path_ready")
        )
        source_state = (
            "Ready — proposal reconstruction"
            if attrs["hybrid_proposal_path_ready"]
            else source_map.state
        )
        self._hass.states.async_set(_SOURCE_MAP_SENSOR, source_state, attrs)

    entity_attrs = {
        "friendly_name": "KEMS pre-install historical evidence",
        **evidence_state,
        "native_kems_days": len(native_days),
        "baseline_covered_days": len(baseline_days),
        "total_covered_days": len(covered_days),
        "real_hardware_writes": "blocked",
    }
    self._hass.states.async_set(
        _EVIDENCE_SENSOR,
        (
            f"{len(reconstructed_days)} reconstructed days"
            if reconstructed_days
            else "Unavailable"
        ),
        entity_attrs,
    )


def install_alpha720_preinstall_patch() -> None:
    """Install proposal-solar historical evidence around the existing backfill."""
    target = backfill.AgileHistoryBackfill
    current = target.async_records
    if getattr(current, "_kems_alpha720_preinstall", False):
        return
    original_records = current

    async def records_with_alpha720(
        self,
        *,
        native_records: list[Snapshot],
        now: datetime,
        tariff: TariffSettings,
        config: SimulationConfig,
    ) -> list[Snapshot]:
        baseline = await original_records(
            self,
            native_records=native_records,
            now=now,
            tariff=tariff,
            config=config,
        )
        local_day = now.astimezone(backfill.LONDON).date()
        if getattr(self, "_kems_alpha720_evidence_day", None) != local_day:
            evidence = await _async_build_evidence(
                self,
                baseline_records=baseline,
                now=now,
                tariff=tariff,
                config=config,
            )
            self._kems_alpha720_evidence_day = local_day
            self._kems_alpha720_evidence_records = evidence.records
            self._kems_alpha720_evidence_state = evidence.state or {}
        evidence_records = tuple(
            getattr(self, "_kems_alpha720_evidence_records", ()) or ()
        )
        evidence_state = dict(getattr(self, "_kems_alpha720_evidence_state", {}) or {})
        merged = backfill._merge_native_and_backfill(baseline, list(evidence_records))
        _overlay_diagnostics(
            self,
            native_records=native_records,
            baseline_records=baseline,
            evidence_records=evidence_records,
            evidence_state=evidence_state,
            now=now,
        )
        return merged

    records_with_alpha720._kems_alpha720_preinstall = True
    target.async_records = records_with_alpha720

    shutdown = target.async_shutdown
    if not getattr(shutdown, "_kems_alpha720_preinstall", False):
        original_shutdown = shutdown

        async def shutdown_with_alpha720(self) -> None:
            await original_shutdown(self)
            self._hass.states.async_remove(_EVIDENCE_SENSOR)

        shutdown_with_alpha720._kems_alpha720_preinstall = True
        target.async_shutdown = shutdown_with_alpha720
