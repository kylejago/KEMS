"""Incremental learning and forecasting for KEMS."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from statistics import fmean

from .models import LearnedState, Snapshot

SLOT_MINUTES = 15
MIN_READY_DAYS = 7
TARGET_CONFIDENCE_DAYS = 30
EXPECTED_RECORDS_PER_DAY = 288


@dataclass(slots=True)
class _SlotValues:
    """Values collected for one day-type/time slot."""

    house_load: list[float]
    solar_power: list[float]
    grid_import: list[float]


def _slot_key(timestamp: datetime) -> tuple[str, int]:
    """Return weekday/weekend and quarter-hour slot index."""
    day_type = "weekend" if timestamp.weekday() >= 5 else "weekday"
    slot = (timestamp.hour * 60 + timestamp.minute) // SLOT_MINUTES
    return day_type, slot


def _mean(values: list[float]) -> float | None:
    """Return a rounded mean when values are available."""
    if not values:
        return None
    return round(fmean(values), 3)


class LearningEngine:
    """Learn rolling load/solar profiles without controlling equipment."""

    def analyse(self, records: list[Snapshot], now: datetime) -> LearnedState:
        """Build a learned state from retained observation history."""
        if not records:
            return LearnedState()

        profiles: dict[tuple[str, int], _SlotValues] = defaultdict(
            lambda: _SlotValues([], [], [])
        )
        days = {record.timestamp.date() for record in records}
        import_rates: list[float] = []
        all_loads: list[float] = []

        for record in records:
            slot = profiles[_slot_key(record.timestamp)]
            if record.house_load_kw is not None:
                load = max(record.house_load_kw, 0.0)
                slot.house_load.append(load)
                all_loads.append(load)
            elif record.grid_import_kw is not None:
                load = max(record.grid_import_kw, 0.0)
                slot.house_load.append(load)
                all_loads.append(load)
            if record.solar_power_kw is not None:
                slot.solar_power.append(max(record.solar_power_kw, 0.0))
            if record.grid_import_kw is not None:
                slot.grid_import.append(max(record.grid_import_kw, 0.0))
            if record.current_import_rate is not None:
                import_rates.append(record.current_import_rate)

        current = profiles.get(_slot_key(now))
        typical_load = _mean(current.house_load) if current else None
        typical_solar = _mean(current.solar_power) if current else None
        typical_grid = _mean(current.grid_import) if current else None
        fallback_load = typical_load or _mean(all_loads)

        latest = records[-1]
        predicted_until_offpeak = self._predict_energy_until_offpeak(
            profiles,
            now,
            latest.next_offpeak_start,
            fallback_load,
        )
        local_tz = now.tzinfo
        tomorrow_date = now.date() + timedelta(days=1)
        end_today = datetime.combine(tomorrow_date, time.min, tzinfo=local_tz)
        end_tomorrow = end_today + timedelta(days=1)
        predicted_remaining_today = self._predict_energy_window(
            profiles,
            now,
            end_today,
            fallback_load,
        )
        predicted_tomorrow = self._predict_energy_window(
            profiles,
            end_today,
            end_tomorrow,
            fallback_load,
        )
        predicted_tomorrow_hourly = self._predict_hourly_energy(
            profiles,
            end_today,
            fallback_load,
        )

        useful_records = sum(
            1
            for record in records
            if record.house_load_kw is not None
            or record.grid_import_kw is not None
            or record.solar_power_kw is not None
        )
        first_timestamp = min(record.timestamp for record in records)
        elapsed_days = max((now - first_timestamp).total_seconds() / 86400, 0.0)
        expected_records = max(elapsed_days * EXPECTED_RECORDS_PER_DAY, 1.0)
        sample_confidence = min(useful_records / expected_records, 1.0)
        time_confidence = min(elapsed_days / TARGET_CONFIDENCE_DAYS, 1.0)
        confidence = round(
            100 * time_confidence * (0.5 + 0.5 * sample_confidence),
            1,
        )

        return LearnedState(
            days_observed=len(days),
            elapsed_observation_days=round(elapsed_days, 2),
            samples=len(records),
            data_coverage=round(100 * sample_confidence, 1),
            confidence=confidence,
            ready=(elapsed_days >= MIN_READY_DAYS and useful_records >= 96),
            typical_house_load_kw=typical_load,
            typical_solar_power_kw=typical_solar,
            typical_grid_import_kw=typical_grid,
            predicted_energy_until_offpeak_kwh=predicted_until_offpeak,
            predicted_house_energy_remaining_today_kwh=predicted_remaining_today,
            predicted_house_energy_tomorrow_kwh=predicted_tomorrow,
            predicted_house_tomorrow_hourly_kwh=predicted_tomorrow_hourly,
            average_import_rate_pence=_mean(import_rates),
            profile_slots=len(profiles),
        )

    def _predict_hourly_energy(
        self,
        profiles: dict[tuple[str, int], _SlotValues],
        day_start: datetime,
        fallback_load_kw: float | None,
    ) -> tuple[float, ...]:
        """Return 24 learned hourly house-energy values for one local day."""
        values: list[float] = []
        for hour in range(24):
            start = day_start + timedelta(hours=hour)
            end = start + timedelta(hours=1)
            energy = self._predict_energy_window(profiles, start, end, fallback_load_kw)
            values.append(round(float(energy or 0.0), 3))
        return tuple(values)

    def _predict_energy_until_offpeak(
        self,
        profiles: dict[tuple[str, int], _SlotValues],
        now: datetime,
        next_offpeak_start: datetime | None,
        fallback_load_kw: float | None,
    ) -> float | None:
        """Predict all remaining house energy before the next cheap period."""
        if next_offpeak_start is None or next_offpeak_start <= now:
            return None
        if next_offpeak_start - now > timedelta(hours=24):
            return None
        return self._predict_energy_window(
            profiles,
            now,
            next_offpeak_start,
            fallback_load_kw,
        )

    def _predict_energy_window(
        self,
        profiles: dict[tuple[str, int], _SlotValues],
        start: datetime,
        end: datetime,
        fallback_load_kw: float | None,
    ) -> float | None:
        """Predict house energy over an arbitrary local-time window."""
        if end <= start:
            return 0.0
        cursor = start
        predicted = 0.0
        seen = 0
        while cursor < end:
            values = profiles.get(_slot_key(cursor))
            load = _mean(values.house_load) if values else None
            if load is None:
                load = fallback_load_kw
            if load is not None:
                interval_minutes = min(
                    SLOT_MINUTES,
                    max((end - cursor).total_seconds() / 60, 0.0),
                )
                predicted += load * interval_minutes / 60
                seen += 1
            cursor += timedelta(minutes=SLOT_MINUTES)
        return round(predicted, 3) if seen else None
