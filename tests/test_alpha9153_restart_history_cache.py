"""Alpha9.153: restart-safe, exact-input, settled-day-only replay cache."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from runpy import run_path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
CACHE = run_path(str(KEMS / "kems_core" / "agile_historical_replay_cache.py"))
HistoricalReplayCache = CACHE["HistoricalReplayCache"]


def _inputs(energy=1.5, price=12.0, soc=65.0):
    return (
        [{"energy": energy}],
        {"reserve": 15},
        {"tariff": 6.6},
        soc,
        64.0,
        None,
        [{"rate": price}],
    )


def test_round_trip_restart_skips_recalculation_and_isolates_mutation() -> None:
    original = HistoricalReplayCache()
    day = date(2026, 10, 26)
    today = date(2026, 10, 28)
    calls = []
    value = original.evaluate(
        day=day,
        today=today,
        projection=False,
        inputs=_inputs(),
        calculate=lambda: calls.append(1)
        or {"agile_smart_export": {"ending_soc_percent": 60.0}},
    )
    assert value["agile_smart_export"]["ending_soc_percent"] == 60.0
    assert original.needs_persist
    persisted = json.loads(json.dumps(original.export_state()))
    original.mark_persisted()
    assert not original.needs_persist

    restarted = HistoricalReplayCache()
    restarted.restore_state(persisted)
    assert restarted.status["restored_days"] == 1
    result = restarted.get_cached(
        day=day, today=today, projection=False, inputs=_inputs()
    )
    assert result == value
    result["agile_smart_export"]["ending_soc_percent"] = 1.0
    assert (
        restarted.get_cached(day=day, today=today, projection=False, inputs=_inputs())[
            "agile_smart_export"
        ]["ending_soc_percent"]
        == 60.0
    )
    assert len(calls) == 1
    assert not restarted.needs_persist


def test_changed_historical_records_prices_soc_tariff_and_config_invalidate() -> None:
    cache = HistoricalReplayCache()
    day = date(2026, 10, 26)
    today = date(2026, 10, 28)
    cache.evaluate(
        day=day,
        today=today,
        projection=False,
        inputs=_inputs(),
        calculate=lambda: {"ready": True},
    )
    restored = HistoricalReplayCache()
    restored.restore_state(json.loads(json.dumps(cache.export_state())))
    assert restored.get_cached(day=day, today=today, projection=False, inputs=_inputs())
    for modified in (
        _inputs(energy=2.0),
        _inputs(price=13.0),
        _inputs(soc=66.0),
        (
            [{"energy": 1.5}],
            {"reserve": 16},
            {"tariff": 6.6},
            65.0,
            64.0,
            None,
            [{"rate": 12.0}],
        ),
        (
            [{"energy": 1.5}],
            {"reserve": 15},
            {"tariff": 6.7},
            65.0,
            64.0,
            None,
            [{"rate": 12.0}],
        ),
    ):
        assert (
            restored.get_cached(day=day, today=today, projection=False, inputs=modified)
            is None
        )


def test_restored_cache_never_serves_current_day_or_tomorrow() -> None:
    cache = HistoricalReplayCache()
    old_day = date(2026, 10, 26)
    today = date(2026, 10, 28)
    cache.evaluate(
        day=old_day,
        today=today,
        projection=False,
        inputs=_inputs(),
        calculate=lambda: {"ready": True},
    )
    restored = HistoricalReplayCache()
    restored.restore_state(cache.export_state())
    for day, projection in (
        (old_day, True),
        (today, False),
        (date(2026, 10, 29), False),
    ):
        assert (
            restored.get_cached(
                day=day, today=today, projection=projection, inputs=_inputs()
            )
            is None
        )


def test_version_mismatch_corruption_and_capacity_fail_closed() -> None:
    cache = HistoricalReplayCache(max_days=2)
    for day in (date(2026, 10, 24), date(2026, 10, 25), date(2026, 10, 26)):
        cache.evaluate(
            day=day,
            today=date(2026, 10, 28),
            projection=False,
            inputs=_inputs(),
            calculate=lambda: {"ready": True},
        )
    assert cache.status["cached_days"] == 2
    payload = cache.export_state()
    assert len(payload["entries"]) == 2
    mismatch = HistoricalReplayCache()
    mismatch.restore_state({**payload, "format": "previous-release"})
    assert mismatch.status["restored_days"] == 0
    damaged = HistoricalReplayCache()
    damaged.restore_state(
        {
            **payload,
            "entries": [
                {"day": "2026-10-26", "sha256": "garbage", "result": {"ready": True}}
            ],
        }
    )
    assert damaged.status["restored_days"] == 0


def test_store_wiring_never_changes_physical_control_or_today_evaluation() -> None:
    source = (KEMS / "agile_smart_export.py").read_text()
    runtime = (KEMS / "agile_smart_export_runtime_base.py").read_text()
    coordinator = (KEMS / "coordinator.py").read_text()
    assert 'cache.restore_state(data.get("historical_replay_cache"))' in source
    assert '"historical_replay_cache": (' in source
    assert "cache.needs_persist" in source
    assert "cache.mark_persisted()" in source
    assert "self._last_analysis = now_utc" in runtime
    assert "return await super().async_update(" in runtime
    assert "self._historical_replay_cache.get_cached(" in runtime
    assert "if day < today_date and day.isoformat() in batched_results:" in source
    assert "today = calculated.get(local_now.date().isoformat())" in source
    assert "guard_paid_agile_physical_export(" in coordinator
    assert "await self._foxess_control.async_update(" in coordinator


def test_alpha9153_version_and_no_auto_install() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())
    assert manifest["version"] == "0.9.0-alpha9.164"
    assert bundle["maintenance"]["reason"].startswith("Alpha9.164:")
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.4"
    assert (
        "no changes to chronological soc carry"
        in bundle["maintenance"]["reason"].lower()
    )
