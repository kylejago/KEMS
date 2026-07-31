"""Incremental learning and forecasting for KEMS."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean

from .models import LearnedState, Snapshot

SLOT_MINUTES = 15
MIN_READY_DAYS = 7
TARGET_CONFIDENCE_DAYS = 30


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

        useful_records = sum(
            1
            for record in records
            if record.house_load_kw is not None
            or record.grid_import_kw is not None
            or record.solar_power_kw is not None
        )
        day_confidence = min(len(days) / TARGET_CONFIDENCE_DAYS, 1.0)
        sample_confidence = min(useful_records / (len(days) * 48 or 1), 1.0)
        confidence = round(100 * day_confidence * (0.5 + 0.5 * sample_confidence), 1)

        return LearnedState(
            days_observed=len(days),
            samples=len(records),
            confidence=confidence,
            ready=len(days) >= MIN_READY_DAYS and useful_records >= 96,
            typical_house_load_kw=typical_load,
            typical_solar_power_kw=typical_solar,
            typical_grid_import_kw=typical_grid,
            predicted_energy_until_offpeak_kwh=predicted_until_offpeak,
            average_import_rate_pence=_mean(import_rates),
            profile_slots=len(profiles),
        )

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

        cursor = now
        predicted = 0.0
        seen = 0
        while cursor < next_offpeak_start:
            values = profiles.get(_slot_key(cursor))
            load = _mean(values.house_load) if values else None
            if load is None:
                load = fallback_load_kw
            if load is not None:
                interval_minutes = min(
                    SLOT_MINUTES,
                    max((next_offpeak_start - cursor).total_seconds() / 60, 0.0),
                )
                predicted += load * interval_minutes / 60
                seen += 1
            cursor += timedelta(minutes=SLOT_MINUTES)

        return round(predicted, 3) if seen else None
