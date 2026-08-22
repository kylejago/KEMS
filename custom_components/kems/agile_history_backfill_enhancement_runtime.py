"""Enhanced Agile history backfill diagnostics and Energy-dashboard fallback."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from homeassistant.components.energy.data import async_get_manager
from homeassistant.exceptions import HomeAssistantError

from . import agile_history_backfill as base
from .kems_core import SimulationConfig, Snapshot
from .tariff import TariffSettings


class EnhancedAgileHistoryBackfill(base.AgileHistoryBackfill):
    """Add transparent source diagnostics and an energy-counter fallback."""

    async def _async_refresh(
        self,
        *,
        native_records: list[Snapshot],
        now: datetime,
        tariff: TariffSettings,
        config: SimulationConfig,
    ) -> None:
        """Try direct power statistics first, then Energy dashboard counters."""
        await super()._async_refresh(
            native_records=native_records,
            now=now,
            tariff=tariff,
            config=config,
        )

        diagnostics = await self._async_direct_diagnostics(now)
        if int(self._state.get("ha_statistics_backfilled_days") or 0) > 0:
            self._augment_state(
                {
                    "backfill_method": "direct_power_statistics",
                    "energy_fallback_used": False,
                    "direct_source_diagnostics": diagnostics,
                }
            )
            return

        recovered = await self._async_energy_dashboard_fallback(
            native_records=native_records,
            now=now,
            tariff=tariff,
            config=config,
            direct_diagnostics=diagnostics,
        )
        if not recovered:
            self._augment_state(
                {
                    "backfill_method": "none",
                    "energy_fallback_used": False,
                    "direct_source_diagnostics": diagnostics,
                }
            )

    async def _async_direct_diagnostics(self, now: datetime) -> dict[str, Any]:
        """Show which configured power sources actually expose retained statistics."""
        sources = self._source_entities()
        if not sources or not self._hass.services.has_service(
            "recorder", "get_statistics"
        ):
            return {
                key: self._source_descriptor(entity_id, [])
                for key, entity_id in sources.items()
            }

        start = datetime.combine(
            now.date() - timedelta(days=base.TARGET_DAYS),
            time.min,
            tzinfo=base.LONDON,
        ).astimezone(UTC)
        end = datetime.combine(now.date(), time.min, tzinfo=base.LONDON).astimezone(UTC)
        try:
            response = await self._hass.services.async_call(
                "recorder",
                "get_statistics",
                {
                    "start_time": start,
                    "end_time": end,
                    "statistic_ids": sorted(set(sources.values())),
                    "period": "day",
                    "types": ["mean", "state"],
                },
                blocking=True,
                return_response=True,
            )
        except (HomeAssistantError, TypeError, ValueError) as err:
            return {
                "query_error": str(err),
                **{
                    key: self._source_descriptor(entity_id, [])
                    for key, entity_id in sources.items()
                },
            }

        statistics = (
            response.get("statistics", {}) if isinstance(response, dict) else {}
        )
        return {
            key: self._source_descriptor(
                entity_id,
                statistics.get(entity_id, []) if isinstance(statistics, dict) else [],
            )
            for key, entity_id in sources.items()
        }

    def _source_descriptor(
        self,
        entity_id: str,
        rows: Any,
    ) -> dict[str, Any]:
        """Return human-readable availability for one configured statistic."""
        state = self._hass.states.get(entity_id)
        attributes = state.attributes if state is not None else {}
        usable_rows = (
            [item for item in rows if isinstance(item, dict)]
            if isinstance(rows, list)
            else []
        )
        starts = [str(item.get("start")) for item in usable_rows if item.get("start")]
        return {
            "entity_id": entity_id,
            "long_term_statistics": bool(usable_rows),
            "historical_rows": len(usable_rows),
            "oldest": starts[0] if starts else None,
            "newest": starts[-1] if starts else None,
            "unit": attributes.get("unit_of_measurement"),
            "device_class": attributes.get("device_class"),
            "state_class": attributes.get("state_class"),
        }

    async def _async_energy_dashboard_fallback(
        self,
        *,
        native_records: list[Snapshot],
        now: datetime,
        tariff: TariffSettings,
        config: SimulationConfig,
        direct_diagnostics: dict[str, Any],
    ) -> bool:
        """Recover hourly replay inputs from HA Energy dashboard energy counters."""
        if not self._hass.services.has_service("recorder", "get_statistics"):
            return False

        manager = await async_get_manager(self._hass)
        preferences = manager.data or manager.default_preferences()
        energy_sources = _energy_sources(preferences.get("energy_sources", []))
        required = bool(
            energy_sources["grid_import"]
            and energy_sources["grid_export"]
            and energy_sources["solar"]
        )
        if not required:
            self._augment_state(
                {
                    "backfill_method": "none",
                    "energy_fallback_used": False,
                    "direct_source_diagnostics": direct_diagnostics,
                    "energy_fallback_sources": energy_sources,
                    "energy_fallback_reason": (
                        "Home Assistant Energy dashboard needs grid import, grid "
                        "export and solar energy statistics for automatic fallback"
                    ),
                }
            )
            return False

        today = now.date()
        start_day = today - timedelta(days=base.TARGET_DAYS)
        native_days = {
            item.timestamp.astimezone(base.LONDON).date()
            for item in native_records
            if start_day <= item.timestamp.astimezone(base.LONDON).date() < today
        }
        missing_days = {
            start_day + timedelta(days=offset) for offset in range(base.TARGET_DAYS)
        } - native_days
        if not missing_days:
            return False

        ids = sorted(
            {
                entity_id
                for values in energy_sources.values()
                for entity_id in values
                if entity_id
            }
        )
        start = datetime.combine(start_day, time.min, tzinfo=base.LONDON).astimezone(
            UTC
        )
        end = datetime.combine(today, time.min, tzinfo=base.LONDON).astimezone(UTC)
        try:
            response = await self._hass.services.async_call(
                "recorder",
                "get_statistics",
                {
                    "start_time": start,
                    "end_time": end,
                    "statistic_ids": ids,
                    "period": "hour",
                    "types": ["change", "mean", "state"],
                },
                blocking=True,
                return_response=True,
            )
        except (HomeAssistantError, TypeError, ValueError) as err:
            self._augment_state(
                {
                    "backfill_method": "none",
                    "energy_fallback_used": False,
                    "direct_source_diagnostics": direct_diagnostics,
                    "energy_fallback_sources": energy_sources,
                    "energy_fallback_reason": f"Energy statistics query failed: {err}",
                }
            )
            return False

        statistics = (
            response.get("statistics", {}) if isinstance(response, dict) else {}
        )
        rows, source_diagnostics = _energy_rows(
            statistics,
            energy_sources=energy_sources,
            units=self._energy_units(ids),
        )
        records: list[Snapshot] = []
        backfilled_days: set[date] = set()
        insufficient_days: set[date] = set()
        source_presence = {
            "house_load_kw": "derived from Energy dashboard counters",
            "solar_power_kw": "derived from Energy dashboard solar energy",
            "grid_import_kw": "derived from Energy dashboard grid import",
            "grid_export_kw": "derived from Energy dashboard grid export",
            "battery_power_kw": "derived from Energy dashboard battery energy",
        }
        if rows.get("battery_soc"):
            source_presence["battery_soc"] = "Energy dashboard battery SOC"

        for day in sorted(missing_days):
            day_records = base._build_day(
                day,
                rows=rows,
                tariff=tariff,
                config=config,
                source_entities=source_presence,
            )
            expected = base._expected_hours(day)
            minimum = max(int(expected * base.MIN_DAY_COVERAGE), 2)
            if len(day_records) - 1 < minimum:
                insufficient_days.add(day)
                continue
            records.extend(day_records)
            backfilled_days.add(day)

        if not backfilled_days:
            self._augment_state(
                {
                    "backfill_method": "none",
                    "energy_fallback_used": False,
                    "direct_source_diagnostics": direct_diagnostics,
                    "energy_fallback_sources": energy_sources,
                    "energy_source_diagnostics": source_diagnostics,
                    "energy_fallback_reason": (
                        "Energy dashboard counters were found but fewer than 75% "
                        "of the required hourly intervals were recoverable per day"
                    ),
                }
            )
            return False

        self._records = sorted(records, key=lambda item: item.timestamp)
        self._publish(
            now=now,
            native_days=native_days,
            backfilled_days=backfilled_days,
            insufficient_days=insufficient_days,
            source_entities=source_presence,
            reason=(
                "Older replay days recovered from Home Assistant Energy dashboard "
                "hourly energy-counter statistics"
            ),
        )
        self._augment_state(
            {
                "backfill_method": "energy_dashboard_counters",
                "energy_fallback_used": True,
                "direct_source_diagnostics": direct_diagnostics,
                "energy_fallback_sources": energy_sources,
                "energy_source_diagnostics": source_diagnostics,
                "backfill_resolution": (
                    "hourly Home Assistant Energy dashboard energy statistics"
                ),
                "energy_fallback_reason": (
                    "Configured power statistics did not recover older days; "
                    "Energy dashboard cumulative counters were used instead"
                ),
            }
        )
        return True

    def _energy_units(self, entity_ids: list[str]) -> dict[str, str | None]:
        """Return current units for Energy dashboard entities where available."""
        result: dict[str, str | None] = {}
        for entity_id in entity_ids:
            state = self._hass.states.get(entity_id)
            result[entity_id] = (
                state.attributes.get("unit_of_measurement")
                if state is not None
                else None
            )
        return result

    def _augment_state(self, values: dict[str, Any]) -> None:
        """Update both diagnostics state and the transient HA entity."""
        self._state.update(values)
        current = self._hass.states.get(base.ENTITY_ID)
        state = current.state if current is not None else "0/365 days"
        self._hass.states.async_set(base.ENTITY_ID, state, dict(self._state))


def _energy_sources(values: Any) -> dict[str, list[str]]:
    """Extract grid/solar/battery energy statistics from Energy preferences."""
    result: dict[str, list[str]] = {
        "grid_import": [],
        "grid_export": [],
        "solar": [],
        "battery_discharge": [],
        "battery_charge": [],
        "battery_soc": [],
    }
    if not isinstance(values, list):
        return result
    for source in values:
        if not isinstance(source, dict):
            continue
        source_type = source.get("type")
        if source_type == "grid":
            _append(result["grid_import"], source.get("stat_energy_from"))
            _append(result["grid_export"], source.get("stat_energy_to"))
        elif source_type == "solar":
            _append(result["solar"], source.get("stat_energy_from"))
        elif source_type == "battery":
            _append(result["battery_discharge"], source.get("stat_energy_from"))
            _append(result["battery_charge"], source.get("stat_energy_to"))
            _append(result["battery_soc"], source.get("stat_soc"))
    return result


def _append(target: list[str], value: Any) -> None:
    """Append one non-empty statistic ID once."""
    if isinstance(value, str) and value and value not in target:
        target.append(value)


def _energy_rows(
    statistics: Any,
    *,
    energy_sources: dict[str, list[str]],
    units: dict[str, str | None],
) -> tuple[dict[str, dict[datetime, float]], dict[str, Any]]:
    """Convert cumulative Energy dashboard counters into hourly KEMS power rows."""
    if not isinstance(statistics, dict):
        return {}, {}

    energy_by_kind: dict[str, dict[datetime, float]] = {
        key: defaultdict(float)
        for key in (
            "grid_import",
            "grid_export",
            "solar",
            "battery_discharge",
            "battery_charge",
        )
    }
    soc_values: dict[datetime, list[float]] = defaultdict(list)
    diagnostics: dict[str, Any] = {}

    for kind, entity_ids in energy_sources.items():
        for entity_id in entity_ids:
            raw_rows = statistics.get(entity_id, [])
            usable = (
                [row for row in raw_rows if isinstance(row, dict)]
                if isinstance(raw_rows, list)
                else []
            )
            starts = [str(row.get("start")) for row in usable if row.get("start")]
            diagnostics[entity_id] = {
                "kind": kind,
                "historical_rows": len(usable),
                "oldest": starts[0] if starts else None,
                "newest": starts[-1] if starts else None,
                "unit": units.get(entity_id),
            }
            for row in usable:
                if row.get("start") is None:
                    continue
                try:
                    timestamp = datetime.fromisoformat(str(row["start"])).astimezone(
                        UTC
                    )
                except ValueError:
                    continue
                if kind == "battery_soc":
                    value = row.get("mean")
                    if value is None:
                        value = row.get("state")
                    try:
                        if value is not None:
                            soc_values[timestamp].append(float(value))
                    except (TypeError, ValueError):
                        pass
                    continue
                value = row.get("change")
                if value is None:
                    continue
                try:
                    energy = _energy_kwh(float(value), units.get(entity_id))
                except (TypeError, ValueError):
                    continue
                energy_by_kind[kind][timestamp] += max(energy, 0.0)

    starts = sorted(
        {timestamp for values in energy_by_kind.values() for timestamp in values}
    )
    rows: dict[str, dict[datetime, float]] = defaultdict(dict)
    for timestamp in starts:
        grid_import = energy_by_kind["grid_import"].get(timestamp)
        grid_export = energy_by_kind["grid_export"].get(timestamp)
        solar = energy_by_kind["solar"].get(timestamp)
        if grid_import is None or grid_export is None or solar is None:
            continue
        battery_discharge = energy_by_kind["battery_discharge"].get(timestamp, 0.0)
        battery_charge = energy_by_kind["battery_charge"].get(timestamp, 0.0)
        house = max(
            solar + grid_import + battery_discharge - grid_export - battery_charge,
            0.0,
        )
        rows["house_load_kw"][timestamp] = house
        rows["solar_power_kw"][timestamp] = solar
        rows["grid_import_kw"][timestamp] = grid_import
        rows["grid_export_kw"][timestamp] = grid_export
        rows["battery_power_kw"][timestamp] = battery_discharge - battery_charge
        if soc_values.get(timestamp):
            rows["battery_soc"][timestamp] = sum(soc_values[timestamp]) / len(
                soc_values[timestamp]
            )
    return dict(rows), diagnostics


def _energy_kwh(value: float, unit: str | None) -> float:
    """Normalise common cumulative-energy units to kWh."""
    text = (unit or "kWh").strip().lower()
    if text == "wh":
        return value / 1000.0
    if text == "mwh":
        return value * 1000.0
    return value


def install_enhanced_backfill() -> None:
    """Upgrade the already-imported backfill class before coordinator creation."""
    target = base.AgileHistoryBackfill
    current = target._async_refresh
    if getattr(current, "_kems_enhanced_backfill", False):
        return

    original_refresh = current
    target._async_direct_diagnostics = (
        EnhancedAgileHistoryBackfill._async_direct_diagnostics
    )
    target._source_descriptor = EnhancedAgileHistoryBackfill._source_descriptor
    target._async_energy_dashboard_fallback = (
        EnhancedAgileHistoryBackfill._async_energy_dashboard_fallback
    )
    target._energy_units = EnhancedAgileHistoryBackfill._energy_units
    target._augment_state = EnhancedAgileHistoryBackfill._augment_state

    async def enhanced_refresh(
        self,
        *,
        native_records: list[Snapshot],
        now: datetime,
        tariff: TariffSettings,
        config: SimulationConfig,
    ) -> None:
        await original_refresh(
            self,
            native_records=native_records,
            now=now,
            tariff=tariff,
            config=config,
        )
        diagnostics = await self._async_direct_diagnostics(now)
        if int(self._state.get("ha_statistics_backfilled_days") or 0) > 0:
            self._augment_state(
                {
                    "backfill_method": "direct_power_statistics",
                    "energy_fallback_used": False,
                    "direct_source_diagnostics": diagnostics,
                }
            )
            return
        recovered = await self._async_energy_dashboard_fallback(
            native_records=native_records,
            now=now,
            tariff=tariff,
            config=config,
            direct_diagnostics=diagnostics,
        )
        if not recovered:
            self._augment_state(
                {
                    "backfill_method": "none",
                    "energy_fallback_used": False,
                    "direct_source_diagnostics": diagnostics,
                }
            )

    enhanced_refresh._kems_enhanced_backfill = True
    target._async_refresh = enhanced_refresh
