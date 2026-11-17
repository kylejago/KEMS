"""Alpha9.220: read-only causes, not an invitation to invent missing kWh."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from kems_core.period_coverage_probe import observation_coverage_probe


def _record(at, *, load=1.0, rate=0.1, tariff_stale=(), grid=True):
    return SimpleNamespace(
        timestamp=at,
        house_load_kw=load,
        grid_import_kw=0.2 if grid else None,
        grid_export_kw=0.0 if grid else None,
        current_import_rate=rate,
        stale_fields=(),
        tariff_stale_fields=tariff_stale,
    )


def test_gap_and_stale_tariff_are_reported_without_changing_samples():
    start = datetime(2026, 11, 16, 12, tzinfo=UTC)
    samples = [
        _record(start, grid=False),
        _record(start + timedelta(minutes=5), tariff_stale=("current_import_rate",)),
        _record(start + timedelta(minutes=20)),
        _record(start + timedelta(minutes=25), load=None, grid=False),
    ]
    before = [record.__dict__.copy() for record in samples]
    report = observation_coverage_probe(samples, start + timedelta(hours=1))
    day = report["day_rows"][0]
    assert day["pair_count"] == 3
    assert day["simulation_replay_eligible_pairs"] == 1
    assert day["missing_or_stale_import_tariff_pairs"] == 1
    assert day["missing_following_load_pairs"] == 1
    assert day["gaps_over_10_minutes"] == 1
    assert day["largest_gap_seconds"] == 900
    assert day["eligible_pairs_without_independent_grid_import"] == 1
    assert day["eligible_pairs_without_independent_grid_export"] == 1
    assert day["source_eligible_pair_percent"] == 33.33
    assert report["not_authoritative_for_period_completion"] is True
    assert report["gap_duration_is_not_metered_kwh"] is True
    assert [record.__dict__ for record in samples] == before


def test_only_recent_calendar_days_are_included_and_pairs_need_two_samples():
    now = datetime(2026, 11, 17, 7, tzinfo=UTC)
    report = observation_coverage_probe(
        [
            _record(datetime(2026, 10, 1, 12, tzinfo=UTC)),
            _record(datetime(2026, 11, 15, 12, tzinfo=UTC)),
            _record(datetime(2026, 11, 17, 7, tzinfo=UTC)),
            _record(datetime(2026, 11, 18, 7, tzinfo=UTC)),
        ],
        now,
    )
    assert [row["date"] for row in report["day_rows"]] == [
        "2026-11-15",
        "2026-11-17",
    ]
    assert all(row["pair_count"] == 0 for row in report["day_rows"])
    assert all(
        row["source_eligible_pair_percent"] is None for row in report["day_rows"]
    )


def test_naive_timestamp_is_not_counted_as_valid_coverage():
    now = datetime(2026, 11, 17, 7, tzinfo=UTC)
    naive = _record(datetime(2026, 11, 17, 6))
    assert observation_coverage_probe([naive], now)["days_with_records"] == 0
