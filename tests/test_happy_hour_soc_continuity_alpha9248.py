"""Alpha9.248: whole-percent FoxESS SOC can be unchanged for hours."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.kems.happy_hour_budget import (
    _bounded_happy_hour_charge_headroom,
)
from custom_components.kems.happy_hour_soc_continuity import (
    HappyHourChargeHeadroomContinuity,
)

T0 = datetime(2026, 11, 22, 6, tzinfo=UTC)


def _sample(now, *, soc_age, battery_kw=0.0, power_age=5.0,
            grid_age=5.0, house_age=5.0, soc=80.0):
    return SimpleNamespace(
        timestamp=now,
        battery_soc=soc,
        battery_power_kw=battery_kw,
        house_load_kw=1.3,
        grid_import_kw=0.0,
        grid_export_kw=0.0,
        source_age_seconds={
            "battery_soc": float(soc_age),
            "battery_power_kw": float(power_age),
            "house_load_kw": float(house_age),
            "grid_import_kw": float(grid_age),
            "grid_export_kw": float(grid_age),
        },
        stale_fields=(),
    )


def _observe(tracker, snapshot):
    return tracker.observe(
        snapshot, now=snapshot.timestamp, capacity=40.0,
        max_charge=7.0, positive_is_discharge=True,
    )


def test_integer_soc_constant_for_over_two_hours_with_fresh_grid_and_power():
    tracker = HappyHourChargeHeadroomContinuity()
    assert _observe(tracker, _sample(T0, soc_age=5))[0] is None
    last_upper = None
    for i in range(1, 241):
        now = T0 + timedelta(seconds=i * 30)
        upper, state = _observe(tracker, _sample(now, soc_age=i * 30 + 5))
        assert state == "continuous_bounded_charge_headroom"
        assert upper is not None
        assert 0.0 <= upper <= 40.0
        last_upper = upper

    # Still useful after two hours, despite a raw SOC age beyond one hour.
    bounded = _bounded_happy_hour_charge_headroom(
        _sample(T0 + timedelta(hours=2), soc_age=7205),
        capacity=40.0, max_charge=7.0,
        continuous_upper_kwh=last_upper,
    )
    assert bounded is not None
    headroom, basis = bounded
    assert headroom > 4.0  # bounded 1 kW/small-gap margin, not 7 kW * 2h
    assert "continuous" in basis


def test_full_charge_margin_preserves_finite_headroom():
    tracker = HappyHourChargeHeadroomContinuity()
    _observe(tracker, _sample(T0, soc_age=5))
    value, _ = _observe(
        tracker, _sample(T0 + timedelta(seconds=30), soc_age=35,
                         battery_kw=-7.0)
    )
    assert value is not None
    assert value >= 32.0  # charged energy is never interpreted as discharge
    later, _ = _observe(
        tracker, _sample(T0 + timedelta(seconds=60), soc_age=65,
                         battery_kw=-7.0)
    )
    assert later is not None and later >= value


def test_old_soc_cold_start_does_not_create_unverified_charge_space():
    tracker = HappyHourChargeHeadroomContinuity()
    value, reason = _observe(tracker, _sample(T0, soc_age=7200))
    assert value is None
    assert reason == "awaiting_recent_soc_anchor_for_cold_start"


def test_power_and_grid_sensor_provenance_fail_closed():
    tracker = HappyHourChargeHeadroomContinuity()
    _observe(tracker, _sample(T0, soc_age=5))
    value, state = _observe(
        tracker, _sample(T0 + timedelta(seconds=30), soc_age=35, grid_age=400)
    )
    assert value is None
    assert state == "missing_current_correlated_physical_telemetry"
    value, _ = _observe(
        tracker, _sample(T0 + timedelta(seconds=60), soc_age=65)
    )
    assert value is None  # restarted tracker requires two physical samples


def test_interrupted_long_gap_does_not_inherit_previous_proof():
    tracker = HappyHourChargeHeadroomContinuity()
    _observe(tracker, _sample(T0, soc_age=5))
    assert _observe(
        tracker, _sample(T0 + timedelta(seconds=30), soc_age=35)
    )[0] is not None
    value, state = _observe(
        tracker, _sample(T0 + timedelta(minutes=20), soc_age=1205)
    )
    assert value is None
    assert state == "observation_gap_needs_new_soc_anchor"


def test_no_hardware_authority_can_be_inferred_from_upper_bound():
    snapshot = _sample(T0, soc_age=8000)
    # A claimed upper bound never overrides absent physical corroboration.
    snapshot.source_age_seconds["grid_import_kw"] = 8000
    snapshot.source_age_seconds["grid_export_kw"] = 8000
    assert _bounded_happy_hour_charge_headroom(
        snapshot, capacity=40, max_charge=7, continuous_upper_kwh=32
    ) is None
    assert _bounded_happy_hour_charge_headroom(
        _sample(T0, soc_age=8000),
        capacity=40, max_charge=7,
    ) is None
