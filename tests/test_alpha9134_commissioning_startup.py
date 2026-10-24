"""Alpha9.134: startup-only empty FoxESS snapshot must not cause control dropout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from kems_core.commissioning_evidence import (
    FOXESS_REQUIRED_TELEMETRY_FIELDS,
    assess_foxess_telemetry_stability,
)


def _sample(n: int, *, missing: tuple[str, ...] = (), stale: tuple[str, ...] = ()):
    values = {field: 2.0 for field in FOXESS_REQUIRED_TELEMETRY_FIELDS}
    for field in missing:
        values[field] = None
    return SimpleNamespace(
        timestamp=datetime(2026, 10, 24, 11, 42, tzinfo=UTC)
        + timedelta(seconds=60 * n),
        stale_fields=stale,
        **values,
    )


def _assess(records):
    return assess_foxess_telemetry_stability(
        records, expected_interval_seconds=60
    )


def test_single_all_empty_startup_sample_does_not_block_valid_proof() -> None:
    empty = _sample(0, missing=FOXESS_REQUIRED_TELEMETRY_FIELDS)
    records = [empty, *(_sample(n) for n in range(1, 19))]
    evidence = _assess(records)
    assert evidence.ready is True
    assert evidence.state == "stable"
    assert evidence.samples == 18
    assert evidence.complete_samples == 18
    assert evidence.completeness_percent == 100.0
    assert evidence.startup_empty_samples_excluded == 1
    assert evidence.to_dict()["startup_empty_samples_excluded"] == 1
    assert evidence.missing_fields == ()


def test_startup_exception_cannot_skip_twelve_good_physical_samples() -> None:
    records = [
        _sample(0, missing=FOXESS_REQUIRED_TELEMETRY_FIELDS),
        *(_sample(n) for n in range(1, 12)),
    ]
    evidence = _assess(records)
    assert not evidence.ready
    assert evidence.state == "collecting"
    assert evidence.samples == 11


def test_later_dropout_is_never_exempt_even_after_valid_startup() -> None:
    empty = _sample(0, missing=FOXESS_REQUIRED_TELEMETRY_FIELDS)
    records = [
        empty,
        *(_sample(n) for n in range(1, 13)),
        _sample(13, missing=FOXESS_REQUIRED_TELEMETRY_FIELDS),
        *(_sample(n) for n in range(14, 20)),
    ]
    evidence = _assess(records)
    assert not evidence.ready
    assert evidence.state == "incomplete"
    assert evidence.samples == 19
    assert evidence.complete_samples == 18
    assert evidence.startup_empty_samples_excluded == 1
    assert evidence.completeness_percent == 94.7


def test_partial_or_stale_initial_physical_observation_remains_counted() -> None:
    for first in (
        _sample(0, missing=("battery_soc",)),
        _sample(0, stale=("battery_soc",)),
    ):
        records = [first, *(_sample(n) for n in range(1, 19))]
        evidence = _assess(records)
        assert not evidence.ready
        assert evidence.state == "incomplete"
        assert evidence.startup_empty_samples_excluded == 0
        assert evidence.samples == 19


def test_startup_exception_never_hides_ongoing_clock_gaps() -> None:
    records = [
        _sample(0, missing=FOXESS_REQUIRED_TELEMETRY_FIELDS),
        *(_sample(n) for n in range(1, 12)),
        _sample(16),
    ]
    evidence = _assess(records)
    assert not evidence.ready
    assert evidence.state == "unstable_interval"
    assert evidence.maximum_gap_seconds == 300.0


def test_first_record_of_rolling_window_is_not_startup() -> None:
    records = [_sample(n) for n in range(65)]
    records[5] = _sample(5, missing=FOXESS_REQUIRED_TELEMETRY_FIELDS)
    evidence = _assess(records)
    assert evidence.ready
    assert evidence.startup_empty_samples_excluded == 0

    records[5] = _sample(5)
    # The first record in the rolling 60-sample window is now unpopulated.
    records[6] = _sample(6, missing=FOXESS_REQUIRED_TELEMETRY_FIELDS)
    evidence = _assess(records)
    assert evidence.ready  # 59/60 = 98.3%, within the existing strict gate
    assert evidence.samples == 60
    assert evidence.complete_samples == 59
    assert evidence.startup_empty_samples_excluded == 0
