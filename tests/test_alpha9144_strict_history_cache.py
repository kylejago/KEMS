"""Alpha9.144: exact-value historical cache fast path, never live authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from kems_core.agile_exact_snapshot_equality import exact_snapshot_values_equal
from kems_core.agile_historical_replay_cache import HistoricalReplayCache

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


@dataclass(slots=True)
class ObservedSample:
    timestamp: datetime
    price: float
    nested: dict[str, object]


def _evaluate(cache, values, *, day=date(2026, 10, 25), now=date(2026, 10, 26)):
    return cache.evaluate(
        day=day,
        today=now,
        projection=False,
        inputs=values,
        calculate=lambda: {"result": "replayed", "slots": [{"value": 4.5}]},
    )


def test_unchanged_historical_inputs_skip_all_repeat_pickle_fingerprints():
    cache = HistoricalReplayCache()
    values = (
        [ObservedSample(datetime(2026, 10, 24, 16), 25.0, {"a": [2, 3]})],
        {"tariff": "Agile", "reserve": 15.0},
        (20.0, 15.0),
    )
    _evaluate(cache, values)
    baseline = cache.status["pickle_fingerprints"]
    assert baseline == 1
    for _ in range(12):
        result = cache.get_cached(
            day=date(2026, 10, 25),
            today=date(2026, 10, 26),
            projection=False,
            inputs=values,
        )
        assert result is not None
        result["slots"][0]["value"] = 99
    assert cache.status["pickle_fingerprints"] == baseline
    assert cache.status["input_snapshot_hits"] == 12
    assert cache.status["input_snapshot_days"] == 1
    assert (
        cache.get_cached(
            day=date(2026, 10, 25),
            today=date(2026, 10, 26),
            projection=False,
            inputs=values,
        )["slots"][0]["value"]
        == 4.5
    )


def test_nested_source_mutation_uses_sha256_and_invalidates_old_result():
    cache = HistoricalReplayCache()
    sample = ObservedSample(
        datetime(2026, 10, 24, 16), 25.0, {"series": [{"power": 2.0}]}
    )
    values = ([sample], {"tariff": "Agile"}, 62.0)
    _evaluate(cache, values)
    sample.nested["series"][0]["power"] = 3.0
    assert (
        cache.get_cached(
            day=date(2026, 10, 25),
            today=date(2026, 10, 26),
            projection=False,
            inputs=values,
        )
        is None
    )
    assert cache.status["pickle_fingerprints"] == 2
    assert cache.status["input_snapshot_hits"] == 0
    _evaluate(cache, values)
    assert cache.status["misses"] == 2
    assert cache.status["input_snapshot_days"] == 1


def test_time_fold_requires_full_fingerprint_on_bst_gmt_transition():
    london = ZoneInfo("Europe/London")
    before = datetime(2026, 10, 25, 1, 30, tzinfo=london, fold=0)
    after = datetime(2026, 10, 25, 1, 30, tzinfo=london, fold=1)
    assert before == after  # Native datetime equality hides this change.
    assert not exact_snapshot_values_equal(before, after)
    cache = HistoricalReplayCache()
    _evaluate(cache, ([ObservedSample(before, 10.0, {})],))
    assert (
        cache.get_cached(
            day=date(2026, 10, 25),
            today=date(2026, 10, 26),
            projection=False,
            inputs=([ObservedSample(after, 10.0, {})],),
        )
        is None
    )


def test_signed_zero_and_dictionary_order_do_not_get_false_fast_hits():
    assert not exact_snapshot_values_equal(-0.0, +0.0)
    assert not exact_snapshot_values_equal({"a": 1, "b": 2}, {"b": 2, "a": 1})
    assert not exact_snapshot_values_equal((1, 2), [1, 2])
    assert not exact_snapshot_values_equal(float("nan"), 0.0)


def test_unsupported_objects_conservatively_fall_back_to_existing_digest():
    assert not exact_snapshot_values_equal(object(), object())
    cache = HistoricalReplayCache()
    inputs = ({"nested": {1, 2, 3}},)
    _evaluate(cache, inputs)
    assert (
        cache.get_cached(
            day=date(2026, 10, 25),
            today=date(2026, 10, 26),
            projection=False,
            inputs=inputs,
        )
        is not None
    )
    assert cache.status["input_snapshot_hits"] == 0
    assert cache.status["pickle_fingerprints"] == 2


def test_input_snapshots_bounded_to_same_lru_day_capacity():
    cache = HistoricalReplayCache(max_days=2)
    for d in [date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)]:
        _evaluate(cache, (str(d),), day=d)
    assert cache.status["cached_days"] == 2
    assert cache.status["input_snapshot_days"] == 2
    assert "2026-10-20" not in cache._input_snapshots


def test_current_day_and_tomorrow_never_use_snapshot_fast_path():
    cache = HistoricalReplayCache()
    today = date(2026, 10, 26)
    for day, projection in ((today, False), (date(2026, 10, 27), True)):
        cache.evaluate(
            day=day,
            today=today,
            projection=projection,
            inputs=("unchanged",),
            calculate=lambda: {"new": True},
        )
        assert (
            cache.get_cached(
                day=day, today=today, projection=projection, inputs=("unchanged",)
            )
            is None
        )
    assert cache.status["input_snapshot_days"] == 0


def test_runtime_physical_authority_remains_independent_of_historical_cache():
    cache = (ROOT / "kems_core/agile_historical_replay_cache.py").read_text()
    runtime = (ROOT / "agile_smart_export_runtime_base.py").read_text()
    coordinator = (ROOT / "coordinator.py").read_text()
    assert "if today is None or day >= today or projection:" in cache
    assert "cached[0] != self._fingerprint(inputs)" in cache
    assert "_historical_cached_comparison" in runtime
    assert "await self._foxess_control.async_update(" in coordinator
    assert "post_shadow_settlement_changed" in coordinator
