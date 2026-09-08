"""Alpha9.14 proposal-solar astronomical-horizon regression contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from kems_core import SimulationConfig, Snapshot
from kems_core.simulation import SimulationEngine
from kems_core.system_profile import (
    FOXHOLE_PROPOSAL_PROFILE,
    SOLAR_HORIZON_ELEVATION_DEGREES,
    _solar_elevation_degrees,
)

LONDON = ZoneInfo("Europe/London")


def _elevation(timestamp: datetime) -> float:
    return _solar_elevation_degrees(
        timestamp,
        FOXHOLE_PROPOSAL_PROFILE.latitude_degrees,
        FOXHOLE_PROPOSAL_PROFILE.longitude_degrees,
    )


def test_proposal_solar_is_zero_before_september_sunrise() -> None:
    """The proposal fallback must not light the panel while it is still dark."""
    before_sunrise = datetime(2026, 9, 8, 6, 30, tzinfo=LONDON)

    assert _elevation(before_sunrise) < SOLAR_HORIZON_ELEVATION_DEGREES
    assert FOXHOLE_PROPOSAL_PROFILE.estimate_power_kw(before_sunrise) == 0.0

    # The same physical instant must stay dark when represented in UTC.
    assert (
        FOXHOLE_PROPOSAL_PROFILE.estimate_power_kw(before_sunrise.astimezone(UTC))
        == 0.0
    )


def test_proposal_solar_resumes_after_astronomical_horizon() -> None:
    """The horizon gate must not suppress valid post-sunrise proposal solar."""
    after_sunrise = datetime(2026, 9, 8, 7, 0, tzinfo=LONDON)

    assert _elevation(after_sunrise) > SOLAR_HORIZON_ELEVATION_DEGREES
    assert FOXHOLE_PROPOSAL_PROFILE.estimate_power_kw(after_sunrise) > 0.0


def test_simulation_fallback_cannot_publish_pre_sunrise_proposal_solar() -> None:
    """The current digital twin/panel feed inherits the same physical gate."""
    before_sunrise = datetime(2026, 9, 8, 6, 30, tzinfo=LONDON)
    snapshot = Snapshot(
        timestamp=before_sunrise,
        solar_power_kw=None,
        stale_fields=("solar_power_kw",),
    )
    config = SimulationConfig(
        proposal_solar_enabled=True,
        proposal_solar_factor=1.0,
        inverter_limit_kw=7.0,
    )

    assert SimulationEngine._simulated_solar_power(snapshot, config) == 0.0


def test_fresh_physical_foxess_solar_remains_authoritative() -> None:
    """Astronomical gating applies only to the proposal fallback, not live PV."""
    before_sunrise = datetime(2026, 9, 8, 6, 30, tzinfo=LONDON)
    snapshot = Snapshot(timestamp=before_sunrise, solar_power_kw=0.12)
    config = SimulationConfig(
        proposal_solar_enabled=True,
        proposal_solar_factor=1.0,
        inverter_limit_kw=7.0,
    )

    assert SimulationEngine._simulated_solar_power(snapshot, config) == 0.12
