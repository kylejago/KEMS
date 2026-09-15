"""Alpha9.46 authoritative FoxESS daily-solar accounting.

KEMS historically reconstructed observed solar energy by integrating the
instantaneous FoxESS PV-power source. That is useful as a fallback, but gaps in
retained observations can under-count a day even when the inverter already owns
an authoritative cumulative "today" energy register.

This compatibility layer keeps instantaneous PV power unchanged for live flow,
learning and routing, while promoting the same-device FoxESS Modbus daily solar
counter to the observed daily-energy authority when it is available. The direct
counter is persisted alongside KEMS snapshots as a backwards-compatible sidecar
field, so completed-day forecast validation can use it without changing the
Snapshot storage schema. Integrated PV remains the fallback and is retained in
diagnostics for discrepancy checks.

This module is reporting/accounting only. It does not alter optimisation,
control eligibility, commissioning, tariff logic or hardware writes.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, datetime
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .collector import Collector
from .kems_core.forecast_validation import ForecastValidationEngine
from .kems_core.models import Snapshot
from .kems_core.simulation import SimulationEngine

_SIDECAR_KEY = "actual_solar_generation_today_kwh"
_INVALID_STATES = {"unknown", "unavailable", "none", ""}
_DIAGNOSTIC_SENSOR_KEYS = frozenset({"data_quality", "simulated_cost_today"})
_DIRECT_BY_TIMESTAMP: dict[str, float] = {}
_LAST_STATUS: dict[str, Any] = {
    "available": False,
    "source": "integrated instantaneous PV fallback",
    "hardware_writes": "blocked",
}


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _normalise(value: Any) -> str:
    """Normalise entity metadata for deterministic matching."""
    return " ".join(
        str(value or "").casefold().replace("_", " ").replace("-", " ").split()
    )


def _energy_kwh(state: State | None) -> float | None:
    """Return one non-negative energy state normalised to kWh."""
    if state is None or state.state.casefold() in _INVALID_STATES:
        return None
    value = _number(state.state)
    if value is None or value < 0:
        return None
    unit = _normalise(state.attributes.get("unit_of_measurement", "")).replace(" ", "")
    if unit in {"kwh", "kilowatthour", "kilowatthours"}:
        return value
    if unit in {"wh", "watthour", "watthours"}:
        return value / 1000.0
    if unit in {"mwh", "megawatthour", "megawatthours"}:
        return value * 1000.0
    return None


def _candidate_score(text: str, unit: str, device_class: str) -> int | None:
    """Score only plausible same-device FoxESS daily PV-energy entities."""
    normalised = _normalise(text)
    compact_unit = _normalise(unit).replace(" ", "")
    if compact_unit not in {
        "kwh",
        "wh",
        "mwh",
        "kilowatthour",
        "kilowatthours",
        "watthour",
        "watthours",
        "megawatthour",
        "megawatthours",
    }:
        return None
    if "today" not in normalised:
        return None
    if not ("solar" in normalised or " pv " in f" {normalised} "):
        return None
    if not any(token in normalised for token in ("generation", "energy", "yield")):
        return None
    if any(
        token in normalised
        for token in (
            "battery",
            "grid import",
            "grid export",
            "feed in",
            "consumption",
            "load",
        )
    ):
        return None

    score = 100
    if "solar generation today" in normalised:
        score += 100
    if "pv generation today" in normalised:
        score += 90
    if "solar" in normalised:
        score += 25
    if "generation" in normalised:
        score += 20
    if _normalise(device_class) == "energy":
        score += 10
    return score


def _solar_power_device_id(hass: HomeAssistant, collector: Collector) -> str | None:
    """Return the device owning KEMS' configured FoxESS PV-power source."""
    foxess = getattr(collector, "_foxess", None)
    entities = getattr(foxess, "_entities", None)
    entity_id = getattr(entities, "solar_power_kw", None)
    if not isinstance(entity_id, str) or not entity_id:
        return None
    entry = er.async_get(hass).async_get(entity_id)
    return None if entry is None else entry.device_id


def _find_daily_solar_entity(
    hass: HomeAssistant,
    collector: Collector,
) -> str | None:
    """Find one unambiguous same-device FoxESS daily solar counter."""
    registry = er.async_get(hass)
    preferred_device = _solar_power_device_id(hass, collector)
    ranked: list[tuple[int, str]] = []

    for entry in registry.entities.values():
        if entry.entity_id.split(".", 1)[0] != "sensor":
            continue
        if str(entry.platform).casefold().strip() != "foxess_modbus":
            continue
        if preferred_device is not None and entry.device_id != preferred_device:
            continue

        state = hass.states.get(entry.entity_id)
        if state is None:
            continue
        text = " ".join(
            (
                entry.entity_id,
                str(entry.original_name or ""),
                str(entry.unique_id or ""),
                str(state.attributes.get("friendly_name", "")),
            )
        )
        score = _candidate_score(
            text,
            str(state.attributes.get("unit_of_measurement", "")),
            str(state.attributes.get("device_class", "")),
        )
        if score is None:
            continue
        ranked.append((score, entry.entity_id))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked:
        return None
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


def _direct_today_kwh(
    hass: HomeAssistant,
    collector: Collector,
    now: datetime,
) -> tuple[str | None, float | None, float | None]:
    """Return today's direct FoxESS total only when it has reported today."""
    entity_id = _find_daily_solar_entity(hass, collector)
    if entity_id is None:
        return None, None, None
    state = hass.states.get(entity_id)
    value = _energy_kwh(state)
    if state is None or value is None:
        return entity_id, None, None

    reported = getattr(state, "last_reported", None) or state.last_updated
    reported_local = dt_util.as_local(reported)
    now_local = dt_util.as_local(now)
    age = max((now - reported).total_seconds(), 0.0)
    if reported_local.date() != now_local.date():
        return entity_id, None, age
    return entity_id, value, age


def _timestamp_key(snapshot: Snapshot) -> str:
    return snapshot.timestamp.isoformat()


def _remember(snapshot: Snapshot, value: float | None) -> None:
    """Attach one direct daily total to the in-memory snapshot sidecar."""
    number = _number(value)
    if number is None or number < 0:
        return
    _DIRECT_BY_TIMESTAMP[_timestamp_key(snapshot)] = number


def _sidecar_value(snapshot: Snapshot) -> float | None:
    return _DIRECT_BY_TIMESTAMP.get(_timestamp_key(snapshot))


def _direct_for_day(
    records: list[Snapshot],
    target_date: date,
    current_snapshot: Snapshot | None = None,
    *,
    require_day_end: bool = False,
) -> float | None:
    """Return the highest retained direct daily total for one local day."""
    candidates: list[tuple[datetime, float]] = []
    for record in [
        *records,
        *([current_snapshot] if current_snapshot is not None else []),
    ]:
        if record.timestamp.date() != target_date:
            continue
        value = _sidecar_value(record)
        if value is None:
            continue
        candidates.append((record.timestamp, value))
    if not candidates:
        return None
    if require_day_end:
        candidates = [item for item in candidates if item[0].hour >= 23]
        if not candidates:
            return None
    return max(value for _, value in candidates)


def _error(predicted: float | None, actual: float | None) -> float | None:
    if predicted is None or actual is None:
        return None
    return round(float(predicted) - float(actual), 3)


def solar_actual_authority_state() -> dict[str, Any]:
    """Return the latest read-only Alpha9.46 accounting diagnostic."""
    return dict(_LAST_STATUS)


def _install_snapshot_sidecar() -> None:
    """Persist direct daily totals without changing the Snapshot dataclass schema."""
    if getattr(Snapshot, "_kems_alpha946_sidecar", False):
        return

    original_to_dict = Snapshot.to_dict
    original_from_dict = Snapshot.from_dict.__func__

    def patched_to_dict(self: Snapshot) -> dict[str, Any]:
        data = original_to_dict(self)
        value = _sidecar_value(self)
        if value is not None:
            data[_SIDECAR_KEY] = round(value, 6)
        return data

    def patched_from_dict(cls, data: dict[str, Any]) -> Snapshot:
        snapshot = original_from_dict(cls, data)
        _remember(snapshot, _number(data.get(_SIDECAR_KEY)))
        return snapshot

    Snapshot.to_dict = patched_to_dict
    Snapshot.from_dict = classmethod(patched_from_dict)
    Snapshot._kems_alpha946_sidecar = True


def _install_collector_capture() -> None:
    """Capture the direct FoxESS day counter beside every retained snapshot."""
    if getattr(Collector, "_kems_alpha946_solar_actual", False):
        return

    original_collect = Collector.collect

    def patched_collect(self: Collector) -> Snapshot:
        snapshot = original_collect(self)
        foxess = getattr(self, "_foxess", None)
        hass = getattr(foxess, "_hass", None)
        if hass is None:
            return snapshot

        entity_id, direct, age = _direct_today_kwh(hass, self, snapshot.timestamp)
        _remember(snapshot, direct)
        _LAST_STATUS.update(
            {
                "available": direct is not None,
                "entity_id": entity_id,
                "direct_today_kwh": round(direct, 3) if direct is not None else None,
                "report_age_seconds": round(age, 1) if age is not None else None,
                "source": (
                    "FoxESS Modbus cumulative solar generation today"
                    if direct is not None
                    else "integrated instantaneous PV fallback"
                ),
                "hardware_writes": "blocked",
            }
        )
        return snapshot

    Collector.collect = patched_collect
    Collector._kems_alpha946_solar_actual = True


def _install_simulation_authority() -> None:
    """Prefer the direct daily counter for observed solar-energy presentation."""
    if getattr(SimulationEngine, "_kems_alpha946_solar_actual", False):
        return

    original = SimulationEngine.simulate_today

    def patched(
        self: SimulationEngine,
        records: list[Snapshot],
        now: datetime,
        config,
        forecast_energy_until_offpeak_kwh: float | None = None,
        current_snapshot: Snapshot | None = None,
        _day_end_boundary: Snapshot | None = None,
        _records_by_day: dict[date, list[Snapshot]] | None = None,
    ):
        result = original(
            self,
            records,
            now,
            config,
            forecast_energy_until_offpeak_kwh,
            current_snapshot=current_snapshot,
            _day_end_boundary=_day_end_boundary,
            _records_by_day=_records_by_day,
        )
        direct = _direct_for_day(records, now.date(), current_snapshot)
        integrated = _number(result.actual_solar_generation_kwh)
        if direct is None:
            if now.date() == dt_util.now().date():
                _LAST_STATUS.update(
                    {
                        "integrated_today_kwh": (
                            round(integrated, 3) if integrated is not None else None
                        ),
                        "difference_kwh": None,
                        "difference_percent": None,
                    }
                )
            return result

        if now.date() == dt_util.now().date():
            difference = direct - integrated if integrated is not None else None
            percent = (
                (difference / direct * 100.0)
                if difference is not None and direct > 0.001
                else None
            )
            _LAST_STATUS.update(
                {
                    "direct_today_kwh": round(direct, 3),
                    "integrated_today_kwh": (
                        round(integrated, 3) if integrated is not None else None
                    ),
                    "difference_kwh": (
                        round(difference, 3) if difference is not None else None
                    ),
                    "difference_percent": (
                        round(percent, 1) if percent is not None else None
                    ),
                    "observed_solar_authority": "direct FoxESS daily counter",
                    "integrated_pv_retained_as_fallback": True,
                }
            )
        return replace(result, actual_solar_generation_kwh=round(direct, 3))

    SimulationEngine.simulate_today = patched
    SimulationEngine._kems_alpha946_solar_actual = True


def _install_forecast_validation_authority() -> None:
    """Use complete retained FoxESS day totals for forecast-vs-actual validation."""
    if getattr(ForecastValidationEngine, "_kems_alpha946_solar_actual", False):
        return

    original = ForecastValidationEngine._validate_day

    def patched(self, target_date, records, forecast):
        result = original(self, target_date, records, forecast)
        direct = _direct_for_day(
            records,
            target_date,
            require_day_end=True,
        )
        if direct is None:
            return result
        actual = round(direct, 3)
        return replace(
            result,
            solar_coverage_percent=100.0,
            actual_solar_kwh=actual,
            forecast_solar_error_kwh=_error(forecast.forecast_solar_kwh, actual),
            open_meteo_error_kwh=_error(forecast.open_meteo_kwh, actual),
            fused_solar_error_kwh=_error(forecast.fused_solar_kwh, actual),
        )

    ForecastValidationEngine._validate_day = patched
    ForecastValidationEngine._kems_alpha946_solar_actual = True


def _install_sensor_diagnostics() -> None:
    """Expose direct-vs-integrated evidence on existing diagnostic surfaces."""
    from . import sensor as sensor_module

    sensor_class = sensor_module.KEMSSensor
    if getattr(sensor_class, "_kems_alpha946_solar_actual", False):
        return
    property_object = sensor_class.extra_state_attributes
    original = property_object.fget
    if original is None:
        return

    def patched(self):
        attributes = original(self)
        if self.entity_description.key not in _DIAGNOSTIC_SENSOR_KEYS:
            return attributes
        result = dict(attributes or {})
        result["solar_generation_actual_authority"] = solar_actual_authority_state()
        return result

    sensor_class.extra_state_attributes = property(patched)
    sensor_class._kems_alpha946_solar_actual = True


def install_alpha946_solar_actual() -> None:
    """Install the Alpha9.46 read-only daily-solar authority once."""
    _install_snapshot_sidecar()
    _install_collector_capture()
    _install_simulation_authority()
    _install_forecast_validation_authority()
    _install_sensor_diagnostics()
