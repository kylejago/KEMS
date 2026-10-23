"""Alpha9.128: historical replay cache and read-only physical budget visibility."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from kems_core.agile_historical_replay_cache import HistoricalReplayCache
from kems_core.agile_plan_budget_reconciliation import reconcile_agile_budget

TODAY = date(2026, 10, 23)
YESTERDAY = date(2026, 10, 22)
ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


def test_exact_identical_historical_replay_only_calculates_once() -> None:
    cache = HistoricalReplayCache()
    calls: list[int] = []

    def replay() -> dict:
        calls.append(1)
        return {"ready": True, "slot_plan": [{"value": 4}]}

    first = cache.evaluate(
        day=YESTERDAY,
        today=TODAY,
        projection=False,
        inputs=([1, 2], "config", "price"),
        calculate=replay,
    )
    first["slot_plan"][0]["value"] = 700
    again = cache.evaluate(
        day=YESTERDAY,
        today=TODAY,
        projection=False,
        inputs=([1, 2], "config", "price"),
        calculate=replay,
    )
    assert calls == [1]
    assert again["slot_plan"][0]["value"] == 4
    assert cache.status["hits"] == 1


def test_replay_invalidates_price_soc_config_and_late_backfill() -> None:
    cache = HistoricalReplayCache()
    count = 0

    def replay() -> dict:
        nonlocal count
        count += 1
        return {"ready": False, "count": count}

    for records, price, soc in (
        ([1], 8.0, 25.0),
        ([1], 8.0, 25.0),
        ([1, 2], 8.0, 25.0),
        ([1, 2], 8.2, 25.0),
        ([1, 2], 8.2, 24.9),
    ):
        cache.evaluate(
            day=YESTERDAY,
            today=TODAY,
            projection=False,
            inputs=(records, price, soc),
            calculate=replay,
        )
    assert count == 4
    assert cache.status["misses"] == 4


def test_live_day_and_projection_never_cached() -> None:
    cache = HistoricalReplayCache()
    calls: list[int] = []
    for day, projection in (
        (TODAY, False),
        (TODAY, False),
        (YESTERDAY, True),
        (YESTERDAY, True),
    ):
        cache.evaluate(
            day=day,
            today=TODAY,
            projection=projection,
            inputs=(1,),
            calculate=lambda: calls.append(1) or {"ready": True},
        )
    assert len(calls) == 4
    assert cache.status["cached_days"] == 0
    assert cache.status["live_evaluations"] == 4


def test_cache_bounded_by_days() -> None:
    cache = HistoricalReplayCache(max_days=2)
    for offset in (3, 2, 1):
        cache.evaluate(
            day=TODAY - timedelta(days=offset),
            today=TODAY,
            projection=False,
            inputs=(1,),
            calculate=lambda: {"ready": True},
        )
    assert cache.status["cached_days"] == 2


def _sample_budget() -> tuple[dict, dict]:
    now = "2026-10-23T21:17:07.715494+01:00"
    return (
        {
            "rolling_export_plan": {
                "available": True,
                "generated_at": now,
                "physical_planning_evidence": {"available": True},
                "planned_battery_export_kwh": 8.06,
                "protected_house_energy_kwh": 2.306,
            }
        },
        {
            "status": "permitted_with_physical_house_budget",
            "physical_energy_evidence": {"observed_at": now},
            "exportable_physical_energy_kwh": 5.118,
            "protected_home_energy_kwh": 5.032,
            "permitted_export_kw": 6.286,
        },
    )


def test_live_9_127_physical_shortfall_reported_without_command() -> None:
    plan, guard = _sample_budget()
    result = reconcile_agile_budget(plan, guard)
    assert result["status"] == "physical_guard_tighter"
    assert result["plan_above_physical_budget_kwh"] == 2.942
    assert result["extra_guard_house_protection_kwh"] == 2.726
    assert result["dispatch_authority"] == "unchanged_independent_physical_guard"
    assert result["hardware_writes"] == "blocked"


def test_budget_mismatched_scan_and_twin_soc_rejected() -> None:
    plan, guard = _sample_budget()
    guard["physical_energy_evidence"]["observed_at"] = "another scan"
    assert reconcile_agile_budget(plan, guard)["status"] == "unavailable"
    plan, guard = _sample_budget()
    plan["rolling_export_plan"]["physical_planning_evidence"]["available"] = False
    assert reconcile_agile_budget(plan, guard)["status"] == "unavailable"


def test_budget_invalid_numbers_and_guard_greater_does_not_invent_gap() -> None:
    plan, guard = _sample_budget()
    guard["exportable_physical_energy_kwh"] = 9.0
    assert reconcile_agile_budget(plan, guard)["plan_above_physical_budget_kwh"] == 0.0
    guard["exportable_physical_energy_kwh"] = float("nan")
    assert reconcile_agile_budget(plan, guard)["status"] == "unavailable"


def test_integration_preserves_per_scan_rolling_analysis_and_hardware_writes() -> None:
    runtime = (ROOT / "agile_smart_export_runtime_base.py").read_text()
    rolling = (ROOT / "agile_rolling_replan_runtime.py").read_text()
    diagnostics = (ROOT / "diagnostics.py").read_text()
    assert "self._historical_replay_cache.evaluate(" in runtime
    assert "runtime.ANALYSIS_REFRESH = timedelta(0)" in rolling
    assert "async def _async_update_with_rolling(" in rolling
    assert '"agile_budget_reconciliation": reconcile_agile_budget(' in diagnostics
    assert "agile_historical_replay_cache" in diagnostics
    assert "hardware_writes" not in runtime
