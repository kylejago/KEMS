"""Alpha9.156: verified historical replay results copy quickly and safely."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from runpy import run_path

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
HistoricalReplayCache = run_path(
    str(ROOT / "kems_core" / "agile_historical_replay_cache.py")
)["HistoricalReplayCache"]


def _historical(cache, *, day=date(2026, 10, 25), inputs=None):
    if inputs is None:
        inputs = ([{"energy": [1.0, 2.0]}], {"tariff": 6.6}, 75.0)
    return cache.evaluate(
        day=day,
        today=date(2026, 10, 28),
        projection=False,
        inputs=inputs,
        calculate=lambda: {
            "ready": True,
            "agile_smart_export": {"ending_soc_percent": 72.0},
            "slot_plan": [
                {"battery_export_kwh": 0.1, "actions": ["export"]} for _ in range(48)
            ],
        },
    )


def test_warm_result_isolation_reuses_binary_copy_but_not_fingerprint():
    cache = HistoricalReplayCache()
    inputs = ([{"energy": [1.0, 2.0]}], {"tariff": 6.6}, 75.0)
    expected = _historical(cache, inputs=inputs)
    assert cache.status["encoded_result_days"] == 1
    assert cache.status["pickle_fingerprints"] == 1
    for _ in range(10):
        value = cache.get_cached(
            day=date(2026, 10, 25),
            today=date(2026, 10, 28),
            projection=False,
            inputs=inputs,
        )
        assert value == expected
        value["slot_plan"][0]["actions"].append("modified")
    assert cache.status["pickle_fingerprints"] == 11
    assert cache.status["fast_result_copies"] == 10
    assert cache.status["fallback_result_copies"] == 0
    assert cache.get_cached(
        day=date(2026, 10, 25),
        today=date(2026, 10, 28),
        projection=False,
        inputs=inputs,
    )["slot_plan"][0]["actions"] == ["export"]


def test_mutable_nested_input_change_still_invalidates_same_scan():
    cache = HistoricalReplayCache()
    data = [{"energy": [1.0, 2.0]}]
    inputs = (data, {"tariff": 6.6}, 75.0)
    _historical(cache, inputs=inputs)
    data[0]["energy"][1] = 4.0
    assert (
        cache.get_cached(
            day=date(2026, 10, 25),
            today=date(2026, 10, 28),
            projection=False,
            inputs=inputs,
        )
        is None
    )
    assert cache.status["pickle_fingerprints"] == 2
    assert cache.status["hits"] == 0
    _historical(cache, inputs=inputs)
    assert cache.status["misses"] == 2


def test_restore_remains_version_one_json_results_and_exact_sha():
    original = HistoricalReplayCache()
    expected = _historical(original)
    persisted = original.export_state()
    assert "result" in persisted["entries"][0]
    assert "sha256" in persisted["entries"][0]
    assert "pickle" not in persisted["entries"][0]
    restored = HistoricalReplayCache()
    restored.restore_state(persisted)
    assert restored.status["restored_days"] == 1
    assert restored.status["encoded_result_days"] == 1
    observed = restored.get_cached(
        day=date(2026, 10, 25),
        today=date(2026, 10, 28),
        projection=False,
        inputs=([{"energy": [1.0, 2.0]}], {"tariff": 6.6}, 75.0),
    )
    assert observed == expected
    assert restored.status["fast_result_copies"] == 1
    assert not restored.needs_persist


def test_result_copy_falls_back_when_value_cannot_be_pickled():
    cache = HistoricalReplayCache()

    def local_function():
        return 3

    inputs = ({"kwh": 3},)
    value = cache.evaluate(
        day=date(2026, 10, 25),
        today=date(2026, 10, 28),
        projection=False,
        inputs=inputs,
        calculate=lambda: {"callable": local_function, "items": [1]},
    )
    assert value["items"] == [1]
    assert cache.status["encoded_result_days"] == 0
    result = cache.get_cached(
        day=date(2026, 10, 25),
        today=date(2026, 10, 28),
        projection=False,
        inputs=inputs,
    )
    assert result["items"] == [1]
    result["items"].append(9)
    assert cache.status["fast_result_copies"] == 0
    assert cache.status["fallback_result_copies"] == 1


def test_bounded_eviction_prunes_binary_results():
    cache = HistoricalReplayCache(max_days=2)
    for n in (24, 25, 26):
        _historical(cache, day=date(2026, 10, n))
    assert cache.status["cached_days"] == 2
    assert cache.status["encoded_result_days"] == 2
    exported = cache.export_state()
    assert [row["day"] for row in exported["entries"]] == [
        "2026-10-25",
        "2026-10-26",
    ]


def test_current_day_and_future_are_uncached_and_control_independent():
    cache = HistoricalReplayCache()
    today = date(2026, 10, 28)
    for day in (today, date(2026, 10, 29)):
        cache.evaluate(
            day=day,
            today=today,
            projection=False,
            inputs=([1.0],),
            calculate=lambda: {"fresh": True},
        )
    assert cache.status["cached_days"] == 0
    assert cache.status["encoded_result_days"] == 0
    assert cache.status["fast_result_copies"] == 0
    source = (ROOT / "coordinator.py").read_text()
    assert "guard_paid_agile_physical_export(" in source
    assert "await self._foxess_control.async_update(" in source
