"""Alpha9.48 authoritative FoxESS daily physical-energy accounting.

Alpha9.46 proved that retained instantaneous-power integration can under-count
physical daily energy when observation intervals are missed or capped. FoxESS
Modbus already exposes same-device cumulative "today" counters for the physical
load, grid import/export and battery charge/discharge paths.

This compatibility layer retains instantaneous power as the live-flow,
learning, tariff-cost and fallback authority, while promoting those same-device
FoxESS daily counters to observed daily-energy authority when available.
Direct totals are persisted beside retained snapshots using sidecar fields so
restart/historical replays keep the same observed-energy evidence.

This module is reporting/accounting only. It does not change optimiser
allocation, tariff policy, SOC/control policy, commissioning or hardware writes.
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
from .kems_core.models import Snapshot
from .kems_core.simulation import SimulationEngine

_INVALID_STATES = {"unknown", "unavailable", "none", ""}
_DIAGNOSTIC_SENSOR_KEYS = frozenset({"data_quality", "simulated_cost_today"})

_METRICS: dict[str, dict[str, str]] = {
    "house": {
        "entity_key": "load_energy_today",
        "name": "Load Energy Today",
        "sidecar": "actual_house_consumption_today_kwh",
        "simulation_field": "actual_house_consumption_kwh",
    },
    "grid_import": {
        "entity_key": "grid_consumption_energy_today",
        "name": "Grid Consumption Today",
        "sidecar": "actual_grid_import_today_kwh",
        "simulation_field": "actual_grid_import_kwh",
    },
    "grid_export": {
        "entity_key": "feed_in_energy_today",
        "name": "Feed-in Today",
        "sidecar": "actual_grid_export_today_kwh",
        "simulation_field": "actual_grid_export_kwh",
    },
    "battery_charge": {
        "entity_key": "battery_charge_today",
        "name": "Battery Charge Today",
        "sidecar": "actual_battery_charge_today_kwh",
        "simulation_field": "actual_battery_charge_kwh",
    },
    "battery_discharge": {
        "entity_key": "battery_discharge_today",
        "name": "Battery Discharge Today",
        "sidecar": "actual_battery_discharge_today_kwh",
        "simulation_field": "actual_battery_discharge_kwh",
    },
}

_DIRECT_BY_TIMESTAMP: dict[str, dict[str, float]] = {}
_LAST_STATUS: dict[str, Any] = {
    "source": "FoxESS Modbus cumulative today counters where available",
    "fallback": "integrated instantaneous physical power",
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
    """Normalise metadata for deterministic entity matching."""
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


def _preferred_device_id(hass: HomeAssistant, collector: Collector) -> str | None:
    """Return the device owning KEMS' configured FoxESS telemetry."""
    foxess = getattr(collector, "_foxess", None)
    entities = getattr(foxess, "_entities", None)
    registry = er.async_get(hass)
    for field in (
        "solar_power_kw",
        "house_load_kw",
        "grid_import_kw",
        "grid_export_kw",
        "battery_power_kw",
    ):
        entity_id = getattr(entities, field, None)
        if not isinstance(entity_id, str) or not entity_id:
            continue
        entry = registry.async_get(entity_id)
        if entry is not None and entry.device_id is not None:
            return entry.device_id
    return None


def _candidate_score(
    *,
    text: str,
    entity_key: str,
    expected_name: str,
    unit: str,
    device_class: str,
) -> int | None:
    """Score one plausible FoxESS cumulative-today energy entity."""
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

    key_text = _normalise(entity_key)
    name_text = _normalise(expected_name)
    if key_text not in normalised and name_text not in normalised:
        return None

    score = 100
    if key_text in normalised:
        score += 120
    if name_text in normalised:
        score += 100
    if _normalise(device_class) == "energy":
        score += 10
    if "total" in normalised and "today" not in name_text:
        score -= 50
    return score


def _find_daily_entity(
    hass: HomeAssistant,
    collector: Collector,
    metric: str,
) -> str | None:
    """Find one unambiguous same-device FoxESS daily counter for a metric."""
    spec = _METRICS[metric]
    registry = er.async_get(hass)
    preferred_device = _preferred_device_id(hass, collector)
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
            text=text,
            entity_key=spec["entity_key"],
            expected_name=spec["name"],
            unit=str(state.attributes.get("unit_of_measurement", "")),
            device_class=str(state.attributes.get("device_class", "")),
        )
        if score is not None:
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
    metric: str,
    now: datetime,
) -> tuple[str | None, float | None, float | None]:
    """Read a direct daily counter only when it has reported on this local day."""
    entity_id = _find_daily_entity(hass, collector, metric)
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


def _remember(snapshot: Snapshot, metric: str, value: float | None) -> None:
    """Attach one direct daily total to the in-memory snapshot sidecar."""
    number = _number(value)
    if number is None or number < 0:
        return
    _DIRECT_BY_TIMESTAMP.setdefault(_timestamp_key(snapshot), {})[metric] = number


def _sidecar_value(snapshot: Snapshot, metric: str) -> float | None:
    return _DIRECT_BY_TIMESTAMP.get(_timestamp_key(snapshot), {}).get(metric)


def _direct_for_day(
    records: list[Snapshot],
    target_date: date,
    metric: str,
    current_snapshot: Snapshot | None = None,
) -> float | None:
    """Return the highest retained direct cumulative-today value for one day."""
    values: list[float] = []
    for record in [
        *records,
        *([current_snapshot] if current_snapshot is not None else []),
    ]:
        if dt_util.as_local(record.timestamp).date() != target_date:
            continue
        value = _sidecar_value(record, metric)
        if value is not None:
            values.append(value)
    return max(values) if values else None


def physical_daily_actual_authority_state() -> dict[str, Any]:
    """Return the latest read-only Alpha9.48 physical-energy diagnostic."""
    return dict(_LAST_STATUS)


def _install_snapshot_sidecar() -> None:
    """Persist direct daily counters without changing Snapshot schema."""
    if getattr(Snapshot, "_kems_alpha948_physical_daily", False):
        return

    original_to_dict = Snapshot.to_dict
    original_from_dict = Snapshot.from_dict.__func__

    def patched_to_dict(self: Snapshot) -> dict[str, Any]:
        data = original_to_dict(self)
        for metric, spec in _METRICS.items():
            value = _sidecar_value(self, metric)
            if value is not None:
                data[spec["sidecar"]] = round(value, 6)
        return data

    def patched_from_dict(cls, data: dict[str, Any]) -> Snapshot:
        snapshot = original_from_dict(cls, data)
        for metric, spec in _METRICS.items():
            _remember(snapshot, metric, _number(data.get(spec["sidecar"])))
        return snapshot

    Snapshot.to_dict = patched_to_dict
    Snapshot.from_dict = classmethod(patched_from_dict)
    Snapshot._kems_alpha948_physical_daily = True


def _install_collector_capture() -> None:
    """Capture all available direct FoxESS daily physical-energy counters."""
    if getattr(Collector, "_kems_alpha948_physical_daily", False):
        return

    original_collect = Collector.collect

    def patched_collect(self: Collector) -> Snapshot:
        snapshot = original_collect(self)
        foxess = getattr(self, "_foxess", None)
        hass = getattr(foxess, "_hass", None)
        if hass is None:
            return snapshot

        metrics: dict[str, Any] = {}
        for metric, spec in _METRICS.items():
            entity_id, direct, age = _direct_today_kwh(
                hass,
                self,
                metric,
                snapshot.timestamp,
            )
            _remember(snapshot, metric, direct)
            metrics[metric] = {
                "available": direct is not None,
                "entity_id": entity_id,
                "counter_name": spec["name"],
                "direct_today_kwh": round(direct, 3) if direct is not None else None,
                "report_age_seconds": round(age, 1) if age is not None else None,
                "authority": (
                    "FoxESS Modbus cumulative today counter"
                    if direct is not None
                    else "integrated instantaneous physical power fallback"
                ),
            }

        _LAST_STATUS.update(
            {
                "metrics": metrics,
                "direct_metric_count": sum(
                    1 for item in metrics.values() if item["available"]
                ),
                "expected_metric_count": len(_METRICS),
                "hardware_writes": "blocked",
            }
        )
        return snapshot

    Collector.collect = patched_collect
    Collector._kems_alpha948_physical_daily = True


def _install_simulation_authority() -> None:
    """Promote direct daily physical-energy counters over sampled integration."""
    if getattr(SimulationEngine, "_kems_alpha948_physical_daily", False):
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

        replacements: dict[str, float] = {}
        diagnostics: dict[str, Any] = {}
        for metric, spec in _METRICS.items():
            field = spec["simulation_field"]
            integrated = _number(getattr(result, field, None))
            direct = _direct_for_day(
                records, dt_util.as_local(now).date(), metric, current_snapshot
            )
            difference = (
                direct - integrated
                if direct is not None and integrated is not None
                else None
            )
            previous_metrics = _LAST_STATUS.get("metrics")
            previous = (
                previous_metrics.get(metric)
                if isinstance(previous_metrics, dict)
                and isinstance(previous_metrics.get(metric), dict)
                else {}
            )
            diagnostics[metric] = {
                **previous,
                "direct_today_kwh": round(direct, 3) if direct is not None else None,
                "integrated_today_kwh": (
                    round(integrated, 3) if integrated is not None else None
                ),
                "difference_kwh": (
                    round(difference, 3) if difference is not None else None
                ),
                "authority": (
                    "direct FoxESS daily counter"
                    if direct is not None
                    else "integrated instantaneous physical power fallback"
                ),
            }
            if direct is not None:
                replacements[field] = round(direct, 3)

        if replacements:
            result = replace(result, **replacements)

        if dt_util.as_local(now).date() == dt_util.as_local(dt_util.now()).date():
            solar = _number(result.actual_solar_generation_kwh)
            house = _number(result.actual_house_consumption_kwh)
            grid_import = _number(result.actual_grid_import_kwh)
            grid_export = _number(result.actual_grid_export_kwh)
            battery_charge = _number(result.actual_battery_charge_kwh)
            battery_discharge = _number(result.actual_battery_discharge_kwh)
            balance_residual = None
            if all(
                value is not None
                for value in (
                    solar,
                    house,
                    grid_import,
                    grid_export,
                    battery_charge,
                    battery_discharge,
                )
            ):
                assert solar is not None
                assert house is not None
                assert grid_import is not None
                assert grid_export is not None
                assert battery_charge is not None
                assert battery_discharge is not None
                balance_residual = (
                    solar
                    + grid_import
                    + battery_discharge
                    - house
                    - grid_export
                    - battery_charge
                )

            _LAST_STATUS.update(
                {
                    "metrics": diagnostics,
                    "authority": (
                        "same-device FoxESS cumulative today counters "
                        "with integrated fallback"
                    ),
                    "physical_balance_residual_kwh": (
                        round(balance_residual, 3)
                        if balance_residual is not None
                        else None
                    ),
                    "tariff_cost_authority": (
                        "retained interval tariff accounting; aggregate daily "
                        "energy counters do not invent tariff timing"
                    ),
                    "hardware_writes": "blocked",
                }
            )

        return result

    SimulationEngine.simulate_today = patched
    SimulationEngine._kems_alpha948_physical_daily = True


def _install_sensor_diagnostics() -> None:
    """Expose direct-vs-integrated physical-energy evidence on diagnostics."""
    from . import sensor as sensor_module

    sensor_class = sensor_module.KEMSSensor
    if getattr(sensor_class, "_kems_alpha948_physical_daily", False):
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
        result["physical_daily_actual_authority"] = (
            physical_daily_actual_authority_state()
        )
        return result

    sensor_class.extra_state_attributes = property(patched)
    sensor_class._kems_alpha948_physical_daily = True


def install_alpha948_physical_daily_actual() -> None:
    """Install Alpha9.48 read-only daily physical-energy authority."""
    _install_snapshot_sidecar()
    _install_collector_capture()
    _install_simulation_authority()
    _install_sensor_diagnostics()
