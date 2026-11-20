"""Alpha9.238: exact full-input SHA-256 with compact Snapshot pickling.

The faster path is historical reporting only. It must validate every field,
including nested mutable dictionaries, signed floats and London fold timestamps;
old persisted SHA-256 entries must migrate without recomputing settled days.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from hashlib import sha256
from pickle import HIGHEST_PROTOCOL, dumps
from zoneinfo import ZoneInfo

from kems_core.agile_historical_replay_cache import (
    PERSISTED_REPLAY_FORMAT,
    HistoricalReplayCache,
)
from kems_core.models import Snapshot

TODAY = date(2026, 11, 20)
DAY = date(2026, 11, 19)


def _inputs(*, price: float = 18.2):
    return (
        [
            Snapshot(
                timestamp=datetime(2026, 11, 19, 7, tzinfo=UTC),
                battery_soc=80.0,
                house_load_kw=2.5,
                source_age_seconds={"battery_soc": 16.2},
                intelligent_slot_evidence={"nested": [False, {"power": 2.3}]},
            ),
            Snapshot(
                timestamp=datetime(2026, 11, 19, 7, 30, tzinfo=UTC),
                battery_soc=79.8,
                house_load_kw=2.7,
            ),
        ],
        {"reserve": 15.0, "plan": ["stay", "export"]},
        {"cheap": 6.6},
        50.0,
        49.0,
        None,
        [{"price": price, "valid_from": "2026-11-19T07:00:00Z"}],
        "product",
        "tariff",
    )


def _put(cache, inputs, calculate=None):
    return cache.evaluate(
        day=DAY,
        today=TODAY,
        projection=False,
        inputs=inputs,
        calculate=calculate or (lambda: {"slots": [{"value": 4.5}]}),
    )


def _hit(cache, inputs):
    return cache.get_cached(day=DAY, today=TODAY, projection=False, inputs=inputs)


def test_compact_full_sha_and_mutable_result_isolation() -> None:
    cache = HistoricalReplayCache()
    inputs = _inputs()
    _put(cache, inputs)
    assert cache.status["compact_snapshot_fingerprints"] == 1
    assert cache.status["pickle_fingerprints"] == 1
    restored = _hit(cache, _inputs())
    assert restored is not None
    restored["slots"][0]["value"] = 99
    assert _hit(cache, _inputs())["slots"][0]["value"] == 4.5
    assert cache.status["compact_snapshot_fingerprints"] == 3
    assert len(cache.export_state()["entries"][0]["sha256"]) == 64


def test_every_mutation_and_price_and_carried_soc_invalidates() -> None:
    cache = HistoricalReplayCache()
    inputs = _inputs()
    _put(cache, inputs)
    inputs[0][0].intelligent_slot_evidence["nested"][1]["power"] = 2.4
    assert _hit(cache, inputs) is None
    assert _hit(cache, _inputs(price=18.3)) is None
    changed = list(_inputs())
    changed[3] = 50.1
    assert _hit(cache, tuple(changed)) is None
    changed = _inputs()
    changed[0][0].source_age_seconds["battery_soc"] = 16.3
    assert _hit(cache, changed) is None


def test_signed_zero_and_london_dst_fold_invalidate() -> None:
    london = ZoneInfo("Europe/London")
    inputs = _inputs()
    before = datetime(2026, 10, 25, 1, 30, tzinfo=london, fold=0)
    after = datetime(2026, 10, 25, 1, 30, tzinfo=london, fold=1)
    inputs[0][0].timestamp = before
    _put(cache := HistoricalReplayCache(), inputs)
    inputs[0][0].timestamp = after
    assert _hit(cache, inputs) is None
    inputs = _inputs()
    inputs[0][0].battery_soc = -0.0
    _put(cache := HistoricalReplayCache(), inputs)
    inputs[0][0].battery_soc = +0.0
    assert _hit(cache, inputs) is None


def test_legacy_restored_full_sha_migrates_without_historical_replay() -> None:
    original = _inputs()
    legacy_digest = sha256(dumps(original, protocol=HIGHEST_PROTOCOL)).hexdigest()
    cache = HistoricalReplayCache()
    cache.restore_state(
        {
            "format": PERSISTED_REPLAY_FORMAT,
            "entries": [
                {
                    "day": DAY.isoformat(),
                    "sha256": legacy_digest,
                    "result": {"slots": [{"value": 4.5}]},
                }
            ],
        }
    )
    assert cache.status["legacy_digest_days_pending_migration"] == 1
    assert _hit(cache, _inputs())["slots"][0]["value"] == 4.5
    assert cache.status["legacy_digest_days_pending_migration"] == 0
    assert cache.status["legacy_digest_days_migrated"] == 1
    assert cache.status["misses"] == 0
    assert cache.needs_persist
    state = json.loads(json.dumps(cache.export_state()))
    assert state["entries"][0]["fingerprint_scheme"] == (
        "snapshot_fields_pickle_sha256_v1"
    )
    cache.mark_persisted()
    assert not cache.needs_persist
    restarted = HistoricalReplayCache()
    restarted.restore_state(state)
    assert _hit(restarted, _inputs())["slots"][0]["value"] == 4.5
    assert restarted.status["legacy_digest_days_pending_migration"] == 0


def test_legacy_modified_input_misses_and_recalculates_normally() -> None:
    cache = HistoricalReplayCache()
    digest = sha256(dumps(_inputs(), protocol=HIGHEST_PROTOCOL)).hexdigest()
    cache.restore_state(
        {
            "format": PERSISTED_REPLAY_FORMAT,
            "entries": [
                {"day": DAY.isoformat(), "sha256": digest, "result": {"value": 1}}
            ],
        }
    )
    calls = []
    result = _put(
        cache,
        _inputs(price=19.4),
        calculate=lambda: calls.append(True) or {"value": 2},
    )
    assert calls == [True]
    assert result == {"value": 2}
    assert cache.status["legacy_digest_days_pending_migration"] == 0
    assert cache.status["misses"] == 1


def test_today_and_tomorrow_are_never_cached_and_physical_control_untouched() -> None:
    cache = HistoricalReplayCache()
    _put(cache, _inputs())
    assert (
        cache.get_cached(day=TODAY, today=TODAY, projection=False, inputs=_inputs())
        is None
    )
    assert (
        cache.get_cached(day=DAY, today=TODAY, projection=True, inputs=_inputs())
        is None
    )
