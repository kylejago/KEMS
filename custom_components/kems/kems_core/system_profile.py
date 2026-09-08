"""Solar and storage profile from the accepted installation proposal."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from math import acos, cos, exp, pi, radians, sin
from zoneinfo import ZoneInfo

PROPOSAL_TIMEZONE = ZoneInfo("Europe/London")
SOLAR_HORIZON_ELEVATION_DEGREES = -0.833


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
    latitude_degrees: float
    longitude_degrees: float
    arrays: tuple[SolarArray, ...]
    monthly_generation_kwh: tuple[float, ...]

    def daily_generation_target_kwh(self, timestamp: datetime) -> float:
        """Return proposal-average generation for the timestamp's local month."""
        local = _proposal_local_timestamp(timestamp)
        days = monthrange(local.year, local.month)[1]
        return self.monthly_generation_kwh[local.month - 1] / days

    def estimate_power_kw(
        self,
        timestamp: datetime,
        weather_factor: float = 1.0,
    ) -> float:
        """Estimate proposal solar power using the three roof orientations.

        The proposal curve keeps its accepted monthly energy target, but the
        instantaneous model is now hard-gated by the real astronomical horizon
        for the proposal site. This prevents the digital twin and ESPHome panel
        from claiming PV before sunrise or after sunset when physical FoxESS PV
        telemetry is unavailable.
        """
        local = _proposal_local_timestamp(timestamp)
        if (
            _solar_elevation_degrees(
                local,
                self.latitude_degrees,
                self.longitude_degrees,
            )
            <= SOLAR_HORIZON_ELEVATION_DEGREES
        ):
            return 0.0

        start_hour, end_hour = _daylight_window(local.month)
        hour = local.hour + local.minute / 60 + local.second / 3600
        if hour <= start_hour or hour >= end_hour:
            return 0.0

        daylight = end_hour - start_hour
        fraction = (hour - start_hour) / daylight
        raw = _raw_profile(self.arrays, fraction)
        scale = _normalisation_scale(local.year, local.month)
        power = raw * scale * max(weather_factor, 0.0)
        return round(min(power, self.inverter_limit_kw), 3)


def _proposal_local_timestamp(timestamp: datetime) -> datetime:
    """Return a proposal-site local timestamp without changing legacy naive use."""
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=PROPOSAL_TIMEZONE)
    return timestamp.astimezone(PROPOSAL_TIMEZONE)


def _solar_elevation_degrees(
    timestamp: datetime,
    latitude_degrees: float,
    longitude_degrees: float,
) -> float:
    """Return solar elevation using the NOAA fractional-year approximation."""
    local = _proposal_local_timestamp(timestamp)
    utc = local.astimezone(UTC)
    day_of_year = utc.timetuple().tm_yday
    utc_hour = utc.hour + utc.minute / 60 + utc.second / 3600
    gamma = 2 * pi / 365 * (day_of_year - 1 + (utc_hour - 12) / 24)

    equation_of_time_minutes = 229.18 * (
        0.000075
        + 0.001868 * cos(gamma)
        - 0.032077 * sin(gamma)
        - 0.014615 * cos(2 * gamma)
        - 0.040849 * sin(2 * gamma)
    )
    declination = (
        0.006918
        - 0.399912 * cos(gamma)
        + 0.070257 * sin(gamma)
        - 0.006758 * cos(2 * gamma)
        + 0.000907 * sin(2 * gamma)
        - 0.002697 * cos(3 * gamma)
        + 0.00148 * sin(3 * gamma)
    )

    utc_offset = local.utcoffset()
    utc_offset_minutes = utc_offset.total_seconds() / 60 if utc_offset else 0.0
    local_minutes = local.hour * 60 + local.minute + local.second / 60
    true_solar_minutes = (
        local_minutes
        + equation_of_time_minutes
        + 4 * longitude_degrees
        - utc_offset_minutes
    ) % 1440
    hour_angle_degrees = true_solar_minutes / 4 - 180

    latitude = radians(latitude_degrees)
    hour_angle = radians(hour_angle_degrees)
    cosine_zenith = sin(latitude) * sin(declination) + cos(latitude) * cos(
        declination
    ) * cos(hour_angle)
    cosine_zenith = min(max(cosine_zenith, -1.0), 1.0)
    return 90.0 - (180.0 / pi) * acos(cosine_zenith)


def _daylight_window(month: int) -> tuple[float, float]:
    """Return the proposal curve's South-West UK monthly shaping window."""
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
    name="151 Foxhole Road - LA Renewables KH7 proposal 10439248",
    solar_capacity_kwp=9.66,
    annual_generation_kwh=8016.0,
    inverter_limit_kw=7.0,
    battery_capacity_kwh=56.42,
    usable_battery_capacity_kwh=50.77,
    shading_factor=0.938,
    latitude_degrees=50.35,
    longitude_degrees=-4.70,
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
