"""Regression tests for stale live-source protection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kems_core import (
    ControlConfig,
    ControlEngine,
    SimulationConfig,
    SimulationEngine,
    SimulationState,
    Snapshot,
    assess_quality,
)

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


def test_quality_distinguishes_stale_sources_from_missing_sources() -> None:
    """A stale live meter must reduce quality and remain explicitly visible."""
    snapshot = Snapshot(
        timestamp=NOW,
        current_import_rate=28.3,
        house_load_kw=None,
        grid_import_kw=None,
        stale_fields=("grid_import_kw", "house_load_kw"),
        source_age_seconds={
            "grid_import_kw": 7200.0,
            "house_load_kw": 7200.0,
        },
        source_data_age_seconds=7200.0,
    )

    quality = assess_quality(
        snapshot,
        {"current_import_rate", "house_load_kw", "grid_import_kw"},
    )

    assert quality.available == 1
    assert quality.configured == 3
    assert quality.stale_fields == ("grid_import_kw", "house_load_kw")
    assert quality.max_source_age_seconds == 7200.0
    assert quality.score < 50


def test_control_uses_source_report_age_not_only_snapshot_timestamp() -> None:
    """A newly collected snapshot must still fail safe when its source is stale."""
    snapshot = Snapshot(
        timestamp=NOW,
        current_import_rate=28.3,
        house_load_kw=None,
        grid_import_kw=None,
        stale_fields=("house_load_kw", "grid_import_kw"),
        source_data_age_seconds=600.0,
    )
    simulation = SimulationState(
        ready=True,
        simulated_battery_soc=70.0,
        current_simulated_house_load_kw=2.0,
        current_simulated_solar_power_kw=0.0,
    )

    state = ControlEngine().plan(
        snapshot,
        simulation,
        NOW,
        ControlConfig(stale_data_seconds=180),
    )

    assert state.data_age_seconds == 600.0
    assert state.data_fresh is False
    assert state.plan_safe is False
    assert state.operating_reason == "stale_data_failsafe"
    assert "house_load_kw" in state.blocked_reason


def test_simulation_does_not_integrate_across_stale_power_gap() -> None:
    """Frozen meter readings must not be multiplied across missing intervals."""
    records = [
        Snapshot(
            timestamp=NOW,
            current_import_rate=28.3,
            house_load_kw=2.0,
            grid_import_kw=2.0,
            off_peak=False,
        ),
        Snapshot(
            timestamp=NOW + timedelta(minutes=5),
            current_import_rate=28.3,
            house_load_kw=2.0,
            grid_import_kw=2.0,
            off_peak=False,
        ),
        Snapshot(
            timestamp=NOW + timedelta(minutes=10),
            current_import_rate=28.3,
            house_load_kw=None,
            grid_import_kw=None,
            off_peak=False,
            stale_fields=("house_load_kw", "grid_import_kw"),
            source_data_age_seconds=600.0,
        ),
        Snapshot(
            timestamp=NOW + timedelta(minutes=15),
            current_import_rate=28.3,
            house_load_kw=2.0,
            grid_import_kw=2.0,
            off_peak=False,
        ),
    ]

    state = SimulationEngine().simulate_today(
        records,
        NOW + timedelta(minutes=15),
        SimulationConfig(proposal_solar_enabled=False),
    )

    # Only the first five-minute interval is trustworthy. The two intervals
    # touching the stale sample are deliberately excluded.
    assert state.actual_house_consumption_kwh == 0.167
    assert state.actual_grid_import_kwh == 0.167
    assert state.data_coverage == 33.3


def test_snapshot_round_trip_preserves_freshness_metadata() -> None:
    """Persisted history keeps stale markers across Home Assistant restarts."""
    snapshot = Snapshot(
        timestamp=NOW,
        stale_fields=("house_load_kw",),
        source_age_seconds={"house_load_kw": 301.5},
        source_data_age_seconds=301.5,
    )

    restored = Snapshot.from_dict(snapshot.to_dict())

    assert restored.stale_fields == ("house_load_kw",)
    assert restored.source_age_seconds == {"house_load_kw": 301.5}
    assert restored.source_data_age_seconds == 301.5
