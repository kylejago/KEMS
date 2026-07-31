"""Solar and storage profile from the accepted installation proposal."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from math import exp, pi, sin


@dataclass(frozen=True, slots=True)
class SolarArray:
    """One roof array in the proposed PV system."""

    name: str
    panels: int
    capacity_kwp: float
    azimuth_degrees: int
    tilt_degrees: int
    peak_fraction: float
    width: float


@dataclass(frozen=True, slots=True)
class ProposalSystemProfile:
    """Fixed physical profile used by the proposal simulation."""

    name: str
    solar_capacity_kwp: float
    annual_generation_kwh: float
    inverter_limit_kw: float
    battery_capacity_kwh: float
    usable_battery_capacity_kwh: float
    shading_factor: float
    arrays: tuple[SolarArray, ...]
    monthly_generation_kwh: tuple[float, ...]

    def daily_generation_target_kwh(self, timestamp: datetime) -> float:
        """Return proposal-average generation for the timestamp's month."""
        days = monthrange(timestamp.year, timestamp.month)[1]
        return self.monthly_generation_kwh[timestamp.month - 1] / days

    def estimate_power_kw(
        self,
        timestamp: datetime,
        weather_factor: float = 1.0,
    ) -> float:
        """Estimate proposal solar power using the three roof orientations."""
        start_hour, end_hour = _daylight_window(timestamp.month)
        hour = timestamp.hour + timestamp.minute / 60 + timestamp.second / 3600
        if hour <= start_hour or hour >= end_hour:
            return 0.0

        daylight = end_hour - start_hour
        fraction = (hour - start_hour) / daylight
        raw = _raw_profile(self.arrays, fraction)
        scale = _normalisation_scale(timestamp.year, timestamp.month)
        power = raw * scale * max(weather_factor, 0.0)
        return round(min(power, self.inverter_limit_kw), 3)


def _daylight_window(month: int) -> tuple[float, float]:
    """Return a practical South-West UK monthly daylight window."""
    return {
        1: (8.0, 16.35),
        2: (7.35, 17.25),
        3: (6.35, 18.25),
        4: (5.7, 20.2),
        5: (5.0, 21.0),
        6: (4.7, 21.45),
        7: (4.9, 21.3),
        8: (5.65, 20.55),
        9: (6.35, 19.45),
        10: (7.15, 18.25),
        11: (7.65, 16.55),
        12: (8.15, 16.15),
    }[month]


def _raw_profile(arrays: tuple[SolarArray, ...], fraction: float) -> float:
    """Return an unnormalised orientation-weighted solar curve."""
    daylight_envelope = max(sin(pi * fraction), 0.0) ** 0.85
    total = 0.0
    for array in arrays:
        orientation = exp(-0.5 * ((fraction - array.peak_fraction) / array.width) ** 2)
        total += array.capacity_kwp * daylight_envelope * orientation
    return total


@lru_cache(maxsize=48)
def _normalisation_scale(year: int, month: int) -> float:
    """Scale the curve so its daily energy matches the proposal month."""
    profile = FOXHOLE_PROPOSAL_PROFILE
    start, end = _daylight_window(month)
    minutes = 5
    raw_energy = 0.0
    cursor = start
    while cursor < end:
        fraction = (cursor - start) / (end - start)
        raw_energy += _raw_profile(profile.arrays, fraction) * minutes / 60
        cursor += minutes / 60
    target = profile.monthly_generation_kwh[month - 1] / monthrange(year, month)[1]
    return target / raw_energy if raw_energy > 0 else 0.0


FOXHOLE_PROPOSAL_PROFILE = ProposalSystemProfile(
    name="151 Foxhole Road - LA Renewables proposal 10439248",
    solar_capacity_kwp=9.66,
    annual_generation_kwh=8016.0,
    inverter_limit_kw=10.0,
    battery_capacity_kwh=56.42,
    usable_battery_capacity_kwh=50.77,
    shading_factor=0.938,
    arrays=(
        SolarArray("East", 9, 4.14, 92, 39, 0.34, 0.24),
        SolarArray("West", 9, 4.14, 271, 39, 0.68, 0.24),
        SolarArray("South", 3, 1.38, 181, 44, 0.50, 0.20),
    ),
    monthly_generation_kwh=(
        258.0,
        351.0,
        643.0,
        778.0,
        1027.0,
        1195.0,
        1192.0,
        930.0,
        665.0,
        475.0,
        289.0,
        214.0,
    ),
)
