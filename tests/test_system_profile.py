"""Tests for the LA Renewables proposal system profile."""

from datetime import UTC, datetime, timedelta

from kems_core import FOXHOLE_PROPOSAL_PROFILE


def test_proposal_profile_matches_quoted_hardware() -> None:
    """The shipped profile should match the quoted system."""
    profile = FOXHOLE_PROPOSAL_PROFILE
    assert profile.solar_capacity_kwp == 9.66
    assert profile.inverter_limit_kw == 10.0
    assert profile.battery_capacity_kwh == 56.42
    assert profile.usable_battery_capacity_kwh == 50.77
    assert sum(array.panels for array in profile.arrays) == 21
    # The proposal monthly table is rounded and totals 8,017 kWh, while the
    # quoted MCS annual estimate is 8,016 kWh. Preserve both source values.
    assert sum(profile.monthly_generation_kwh) == 8017.0
    assert profile.annual_generation_kwh == 8016.0


def test_daily_solar_curve_integrates_to_monthly_target() -> None:
    """The three-array power curve should reproduce the proposal daily target."""
    profile = FOXHOLE_PROPOSAL_PROFILE
    start = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    cursor = start
    energy = 0.0
    while cursor < start + timedelta(days=1):
        energy += profile.estimate_power_kw(cursor) * 5 / 60
        cursor += timedelta(minutes=5)

    target = profile.daily_generation_target_kwh(start)
    assert abs(energy - target) < 0.2
    assert (
        max(
            profile.estimate_power_kw(start + timedelta(minutes=minute))
            for minute in range(0, 24 * 60, 5)
        )
        <= 10.0
    )
