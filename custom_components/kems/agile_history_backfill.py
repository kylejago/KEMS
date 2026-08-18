"""Historical Home Assistant statistics backfill for Agile Smart Export.

The normal KEMS history remains the source of truth wherever it exists. This
module only supplies older hourly observations to the read-only Agile replay so
KEMS can extend the comparison using Home Assistant long-term statistics
without accessing Recorder's database directly.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .kems_core import SimulationConfig, Snapshot
from .providers.entity_map import KEMSEntities
from .tariff import TariffSettings, resolve_tariff

LONDON = ZoneInfo("Europe/London")
TARGET_DAYS = 365
MIN_DAY_COVERAGE = 0.75
ENTITY_ID = "sensor.kems_agile_history_backfill"


class AgileHistoryBackfill:
    """Recover older replay inputs from Home Assistant long-term statistics."""

    def __init__(self, hass: HomeAssistant, entities: KEMSEntities) -> None:
        self._hass = hass
        self._entities = entities
        self._last_refresh_day: date | None = None
        self._records: list[Snapshot] = []
        self._state: dict[str, Any] = {}

    @property
    def state(self) -> dict[str, Any]:
        """Return the latest backfill quality report."""
        return dict(self._state)

    async def async_records(
        self,
        *,
        native_records: list[Snapshot],
        now: datetime,
        tariff: TariffSettings,
        config: SimulationConfig,
    ) -> list[Snapshot]:
        """Return native KEMS records plus recoverable older HA statistics."""
        local_now = now.astimezone(LONDON)
        today = local_now.date()
        if self._last_refresh_day != today:
            await self._async_refresh(
                native_records=native_records,
                now=local_now,
                tariff=tariff,
                config=config,
            )
        return _merge_native_and_backfill(native_records, self._records)

    async def _async_refresh(
        self,
        *,
        native_records: list[Snapshot],
        now: datetime,
        tariff: TariffSettings,
        config: SimulationConfig,
    ) -> None:
        """Refresh the rolling 365-day hourly backfill at most once per local day."""
        today = now.date()
        start_day = today - timedelta(days=TARGET_DAYS)
        end_day = today - timedelta(days=1)
        native_days = {
            item.timestamp.astimezone(LONDON).date()
            for item in native_records
            if start_day <= item.timestamp.astimezone(LONDON).date() <= end_day
        }
        requested_days = {
            start_day + timedelta(days=offset) for offset in range(TARGET_DAYS)
        }
        missing_days = requested_days - native_days

        source_entities = self._source_entities()
        house_direct = source_entities.get("house_load_kw")
        can_derive_house = all(
            source_entities.get(key)
            for key in (
                "solar_power_kw",
                "grid_import_kw",
                "grid_export_kw",
                "battery_power_kw",
            )
        )
        required_available = bool(house_direct or can_derive_house)
        if config.proposal_solar_enabled and not source_entities.get("solar_power_kw"):
            required_available = False

        if not missing_days or not required_available:
            self._records = []
            if not missing_days:
                reason = "native KEMS already covers the rolling window"
            else:
                reason = (
                    "required historical house-load/solar statistics "
                    "are not configured"
                )
            self._publish(
                now=now,
                native_days=native_days,
                backfilled_days=set(),
                insufficient_days=missing_days,
                source_entities=source_entities,
                reason=reason,
            )
            self._last_refresh_day = today
            return

        if not self._hass.services.has_service("recorder", "get_statistics"):
            self._records = []
            self._publish(
                now=now,
                native_days=native_days,
                backfilled_days=set(),
                insufficient_days=missing_days,
                source_entities=source_entities,
                reason="Home Assistant recorder.get_statistics is unavailable",
            )
            self._last_refresh_day = today
            return

        statistic_ids = sorted(set(source_entities.values()))
        start = datetime.combine(start_day, time.min, tzinfo=LONDON).astimezone(UTC)
        end = datetime.combine(today, time.min, tzinfo=LONDON).astimezone(UTC)
        try:
            response = await self._hass.services.async_call(
                "recorder",
                "get_statistics",
                {
                    "start_time": start,
                    "end_time": end,
                    "statistic_ids": statistic_ids,
                    "period": "hour",
                    "types": ["mean", "state"],
                },
                blocking=True,
                return_response=True,
            )
        except (HomeAssistantError, ValueError, TypeError) as err:
            self._records = []
            self._publish(
                now=now,
                native_days=native_days,
                backfilled_days=set(),
                insufficient_days=missing_days,
                source_entities=source_entities,
                reason=f"Recorder statistics query failed: {err}",
            )
            self._last_refresh_day = today
            return

        statistics = (
            response.get("statistics", {}) if isinstance(response, dict) else {}
        )
        rows = _normalise_statistics(
            statistics,
            source_entities=source_entities,
            units=self._source_units(source_entities),
        )
        records: list[Snapshot] = []
        backfilled_days: set[date] = set()
        insufficient_days: set[date] = set()
        for day in sorted(missing_days):
            day_records = _build_day(
                day,
                rows=rows,
                tariff=tariff,
                config=config,
                source_entities=source_entities,
            )
            expected = _expected_hours(day)
            minimum = max(int(expected * MIN_DAY_COVERAGE), 2)
            if len(day_records) - 1 < minimum:
                insufficient_days.add(day)
                continue
            records.extend(day_records)
            backfilled_days.add(day)

        self._records = sorted(records, key=lambda item: item.timestamp)
        self._publish(
            now=now,
            native_days=native_days,
            backfilled_days=backfilled_days,
            insufficient_days=insufficient_days,
            source_entities=source_entities,
            reason=(
                "Older replay days recovered from Home Assistant hourly "
                "long-term statistics"
            ),
        )
        self._last_refresh_day = today

    def _source_entities(self) -> dict[str, str]:
        """Return only source entities useful for historical strategy replay."""
        values = {
            "house_load_kw": self._entities.house_load_kw,
            "solar_power_kw": self._entities.solar_power_kw,
            "grid_import_kw": self._entities.grid_import_kw,
            "grid_export_kw": self._entities.grid_export_kw,
            "battery_power_kw": self._entities.battery_power_kw,
            "battery_soc": self._entities.battery_soc,
            "ev_power_kw": self._entities.ev_power_kw,
        }
        return {key: value for key, value in values.items() if value}

    def _source_units(self, sources: dict[str, str]) -> dict[str, str | None]:
        """Read current units so Recorder means can be normalised to KEMS units."""
        result: dict[str, str | None] = {}
        for entity_id in sources.values():
            state = self._hass.states.get(entity_id)
            result[entity_id] = (
                state.attributes.get("unit_of_measurement")
                if state is not None
                else None
            )
        return result

    def _publish(
        self,
        *,
        now: datetime,
        native_days: set[date],
        backfilled_days: set[date],
        insufficient_days: set[date],
        source_entities: dict[str, str],
        reason: str,
    ) -> None:
        """Publish transparent backfill coverage and fidelity metadata."""
        covered = native_days | backfilled_days
        coverage_percent = round(100 * len(covered) / TARGET_DAYS, 1)
        attrs = {
            "friendly_name": "Agile Smart Export historical backfill",
            "target_days": TARGET_DAYS,
            "native_kems_days": len(native_days),
            "ha_statistics_backfilled_days": len(backfilled_days),
            "covered_days": len(covered),
            "coverage_percent": coverage_percent,
            "insufficient_days": len(insufficient_days),
            "earliest_backfilled_day": (
                min(backfilled_days).isoformat() if backfilled_days else None
            ),
            "latest_backfilled_day": (
                max(backfilled_days).isoformat() if backfilled_days else None
            ),
            "source_entities": source_entities,
            "backfill_resolution": "hourly Home Assistant long-term statistics",
            "strategy_fidelity": (
                "native KEMS days retain original five-minute/forecast observations; "
                "backfilled days use hourly historical demand/solar observations"
            ),
            "tariff_fidelity": (
                "normal configured off-peak schedule is reconstructed; historical "
                "Intelligent bonus slots are not invented"
            ),
            "forecast_fidelity": (
                "historical KEMS forecast annotations are unavailable "
                "on backfilled days"
            ),
            "authoritative_native_365": len(native_days) >= TARGET_DAYS,
            "last_refresh": now.isoformat(),
            "reason": reason,
        }
        self._state = dict(attrs)
        self._hass.states.async_set(
            ENTITY_ID,
            f"{len(covered)}/{TARGET_DAYS} days",
            attrs,
        )

    async def async_shutdown(self) -> None:
        """Remove the transient backfill status entity on unload."""
        self._hass.states.async_remove(ENTITY_ID)


def _merge_native_and_backfill(
    native_records: list[Snapshot],
    backfill_records: list[Snapshot],
) -> list[Snapshot]:
    """Prefer native KEMS observations for every day where they exist."""
    native_days = {item.timestamp.astimezone(LONDON).date() for item in native_records}
    older = [
        item
        for item in backfill_records
        if item.timestamp.astimezone(LONDON).date() not in native_days
    ]
    return sorted([*older, *native_records], key=lambda item: item.timestamp)


def _normalise_statistics(
    statistics: Any,
    *,
    source_entities: dict[str, str],
    units: dict[str, str | None],
) -> dict[str, dict[datetime, float]]:
    """Convert Recorder service rows into logical KEMS field/time mappings."""
    if not isinstance(statistics, dict):
        return {}
    entity_to_field = {entity: field for field, entity in source_entities.items()}
    result: dict[str, dict[datetime, float]] = defaultdict(dict)
    for entity_id, statistic_rows in statistics.items():
        field = entity_to_field.get(str(entity_id))
        if field is None or not isinstance(statistic_rows, list):
            continue
        for row in statistic_rows:
            if not isinstance(row, dict) or row.get("start") is None:
                continue
            value = row.get("mean")
            if value is None:
                value = row.get("state")
            if value is None:
                continue
            try:
                timestamp = datetime.fromisoformat(str(row["start"])).astimezone(UTC)
                number = float(value)
            except (TypeError, ValueError):
                continue
            if field.endswith("_kw"):
                number = _power_kw(number, units.get(str(entity_id)))
            result[field][timestamp] = number
    return dict(result)


def _power_kw(value: float, unit: str | None) -> float:
    """Normalise common power units to kW."""
    text = (unit or "kW").strip().lower()
    if text == "w":
        return value / 1000.0
    if text == "mw":
        return value * 1000.0
    return value


def _build_day(
    day: date,
    *,
    rows: dict[str, dict[datetime, float]],
    tariff: TariffSettings,
    config: SimulationConfig,
    source_entities: dict[str, str],
) -> list[Snapshot]:
    """Build one local day of honest hourly replay snapshots."""
    starts = sorted(
        {
            timestamp
            for values in rows.values()
            for timestamp in values
            if timestamp.astimezone(LONDON).date() == day
        }
    )
    records: list[Snapshot] = []
    for timestamp in starts:
        house = _value(rows, "house_load_kw", timestamp)
        solar = _value(rows, "solar_power_kw", timestamp)
        grid_import = _value(rows, "grid_import_kw", timestamp)
        grid_export = _value(rows, "grid_export_kw", timestamp)
        battery_power = _value(rows, "battery_power_kw", timestamp)

        if house is None:
            house = _derive_house_load(
                solar=solar,
                grid_import=grid_import,
                grid_export=grid_export,
                battery_power=battery_power,
                positive_battery_is_discharge=(
                    config.battery_power_positive_is_discharge
                ),
            )
        if house is None:
            continue
        if (
            config.proposal_solar_enabled
            and source_entities.get("solar_power_kw")
            and solar is None
        ):
            continue
        solar = max(float(solar or 0.0), 0.0)
        local = timestamp.astimezone(LONDON)
        resolved = resolve_tariff(
            settings=tariff,
            now=local,
            live_current_import_rate=None,
            live_next_import_rate=None,
            live_current_export_rate=None,
            live_standing_charge=None,
            live_off_peak=None,
            live_intelligent_slot=None,
            live_next_offpeak_start=None,
            live_offpeak_end=None,
            ev_charging=None,
            fallback_export_rate=config.export_rate_pence,
        )
        records.append(
            Snapshot(
                timestamp=timestamp,
                current_import_rate=resolved.current_import_rate,
                next_import_rate=resolved.next_import_rate,
                current_export_rate=resolved.current_export_rate,
                electricity_standing_charge=resolved.electricity_standing_charge,
                off_peak=resolved.off_peak,
                intelligent_slot=False,
                next_offpeak_start=resolved.next_offpeak_start,
                offpeak_end=resolved.offpeak_end,
                house_load_kw=max(float(house), 0.0),
                battery_soc=_value(rows, "battery_soc", timestamp),
                battery_power_kw=battery_power,
                solar_power_kw=solar,
                grid_import_kw=(
                    max(float(grid_import), 0.0) if grid_import is not None else None
                ),
                grid_export_kw=(
                    max(float(grid_export), 0.0) if grid_export is not None else None
                ),
                ev_power_kw=_value(rows, "ev_power_kw", timestamp),
                grid_flow_mode="ha_statistics_backfill",
                forecast_source="ha_statistics_backfill",
                forecast_confidence_percent=0.0,
            )
        )

    if records:
        final_local = datetime.combine(day, time(23, 59, 59), tzinfo=LONDON)
        last = records[-1]
        records.append(
            Snapshot.from_dict(
                {
                    **last.to_dict(),
                    "timestamp": final_local.astimezone(UTC).isoformat(),
                }
            )
        )
    return records


def _derive_house_load(
    *,
    solar: float | None,
    grid_import: float | None,
    grid_export: float | None,
    battery_power: float | None,
    positive_battery_is_discharge: bool,
) -> float | None:
    """Derive house load only when every required net-flow input is available."""
    if any(value is None for value in (solar, grid_import, grid_export, battery_power)):
        return None
    signed_discharge = float(battery_power)
    if not positive_battery_is_discharge:
        signed_discharge *= -1
    return max(
        float(solar) + float(grid_import) - float(grid_export) + signed_discharge,
        0.0,
    )


def _value(
    rows: dict[str, dict[datetime, float]],
    field: str,
    timestamp: datetime,
) -> float | None:
    """Return one exact hourly value."""
    return rows.get(field, {}).get(timestamp)


def _expected_hours(day: date) -> int:
    """Return 23/24/25 hours for a UK local day, including DST changes."""
    start = datetime.combine(day, time.min, tzinfo=LONDON).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=LONDON).astimezone(
        UTC
    )
    return int((end - start).total_seconds() // 3600)
