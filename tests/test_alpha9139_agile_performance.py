"""Alpha9.139 — accelerate historical replay without caching live dispatch."""

from __future__ import annotations

import ast
import importlib.util
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
CORE = ROOT / "custom_components" / "kems"


def _rate_class():
    source = (CORE / "agile_smart_export.py").read_text(encoding="utf-8")
    manager = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.ClassDef) and node.name == "AgileSmartExportManager"
    )
    methods = [
        method
        for method in manager.body
        if isinstance(method, ast.FunctionDef)
        and method.name in {"_index_day_rates", "_day_rates"}
    ]
    assert len(methods) == 2
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            ast.ClassDef(
                name="Indexed",
                bases=[],
                keywords=[],
                body=methods,
                decorator_list=[],
            ),
        ],
        type_ignores=[],
    )
    namespace = {"LONDON": ZoneInfo("Europe/London"), "date": date}
    exec(compile(ast.fix_missing_locations(module), "<rate-index>", "exec"), namespace)
    instance = namespace["Indexed"]()
    instance._rates = []
    instance._day_rate_index_source = None
    instance._day_rate_index = {}
    instance._day_rate_index_builds = 0
    return instance


def _historical_cache():
    path = CORE / "kems_core" / "agile_historical_replay_cache.py"
    spec = importlib.util.spec_from_file_location("isolated_agile_cache", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HistoricalReplayCache()


def test_uk_fall_back_has_50_slots_and_retains_both_repeated_hours():
    obj = _rate_class()
    # Explicit UTC instants distinguish both occurrences of 01:00–02:00.
    start = datetime(2026, 10, 24, 23, tzinfo=UTC)
    slots = [
        SimpleNamespace(
            valid_from=start + timedelta(minutes=30 * n),
            value_inc_vat=float(n),
        )
        for n in range(52)
    ]
    obj._rates = slots
    expected = [
        slot
        for slot in slots
        if slot.valid_from.astimezone(ZoneInfo("Europe/London")).date()
        == date(2026, 10, 25)
    ]
    assert len(expected) == 50
    obj._index_day_rates()
    got = obj._day_rates(date(2026, 10, 25))
    assert got == expected
    assert len({slot.valid_from for slot in got}) == 50
    assert obj._day_rate_index_builds == 1
    assert obj._day_rates(date(2026, 10, 27)) == []


def test_rate_index_preserves_order_price_changes_and_per_pass_invalidation():
    obj = _rate_class()
    initial = datetime(2026, 10, 20, tzinfo=UTC)
    obj._rates = [
        SimpleNamespace(valid_from=initial + timedelta(days=n), value_inc_vat=n)
        for n in (2, 0, 3, 1)
    ]
    obj._index_day_rates()
    assert [x.value_inc_vat for x in obj._day_rates(initial.date())] == [0]
    returned = obj._day_rates(initial.date())
    returned.clear()
    assert len(obj._day_rates(initial.date())) == 1
    updated = SimpleNamespace(valid_from=initial, value_inc_vat=99)
    obj._rates[1] = updated
    obj._index_day_rates()
    assert obj._day_rates(initial.date())[0].value_inc_vat == 99
    obj._rates = [SimpleNamespace(valid_from=initial, value_inc_vat=1.5)]
    # If fetched rates are replaced between passes, never use the old index.
    assert obj._day_rates(initial.date())[0].value_inc_vat == 1.5


def test_price_index_avoids_repeated_full_rate_scans():
    obj = _rate_class()
    seen = {"count": 0}

    class Rate:
        def __init__(self, start):
            self.start = start

        @property
        def valid_from(self):
            seen["count"] += 1
            return self.start

    start = datetime(2026, 1, 1, tzinfo=UTC)
    obj._rates = [Rate(start + timedelta(hours=n)) for n in range(24 * 85)]
    obj._index_day_rates()
    assert seen["count"] == len(obj._rates)
    for n in range(85):
        assert len(obj._day_rates((start + timedelta(days=n)).date())) == 24
    # Old algorithm required 85 * 2,040 timezone conversions per pass.
    assert seen["count"] == 24 * 85


def test_exact_historical_reuse_invalidates_on_nested_input_changes():
    cache = _historical_cache()
    day = date(2026, 10, 20)
    today = date(2026, 10, 25)
    records = [{"load": [1.0, 2.0], "soc": 80}]
    config = {"efficiency": 0.95}
    rates = [{"value": 15.0}]
    inputs = (records, config, rates, 75.0)
    counter = {"calls": 0}

    def calculate():
        counter["calls"] += 1
        return {"number": counter["calls"], "slots": [{"export": 0.0}]}

    def run(**extra):
        return cache.evaluate(
            day=day,
            today=today,
            projection=False,
            inputs=inputs,
            calculate=calculate,
            **extra,
        )

    first = run()
    assert first["number"] == 1
    first["slots"][0]["export"] = 900.0
    second = run()
    assert second["number"] == 1
    assert second["slots"][0]["export"] == 0.0
    records[0]["load"][0] = 5.0
    assert run()["number"] == 2
    rates[0]["value"] = 20.0
    assert run()["number"] == 3
    config["efficiency"] = 0.90
    assert run()["number"] == 4
    assert cache.status["hits"] == 1
    assert cache.status["misses"] == 4
    assert cache.status["pickle_fingerprints"] == 5
    assert cache.status["legacy_fingerprints"] == 0


def test_today_and_tomorrow_remain_completely_uncached():
    cache = _historical_cache()
    counter = {"calls": 0}

    def calc():
        counter["calls"] += 1
        return {"scan": counter["calls"]}

    def run(day, projection=False):
        return cache.evaluate(
            day=day,
            today=date(2026, 10, 25),
            projection=projection,
            inputs=({"state": 1},),
            calculate=calc,
        )

    assert run(date(2026, 10, 25)) == {"scan": 1}
    assert run(date(2026, 10, 25)) == {"scan": 2}
    assert run(date(2026, 10, 26), projection=True) == {"scan": 3}
    assert cache.status["live_evaluations"] == 3
    assert cache.status["pickle_fingerprints"] == 0


def test_non_picklable_historical_provider_uses_legacy_fingerprint():
    cache = _historical_cache()
    counter = {"calls": 0}

    def calc():
        counter["calls"] += 1
        return {"count": counter["calls"]}

    source = lambda: 1
    for _ in range(2):
        result = cache.evaluate(
            day=date(2026, 10, 20),
            today=date(2026, 10, 25),
            projection=False,
            inputs=({"unsupported": source},),
            calculate=calc,
        )
        assert result["count"] == 1
    assert cache.status["legacy_fingerprints"] == 2
    assert cache.status["hits"] == 1


def test_never_substitute_reporting_cache_for_control_gate():
    source = (CORE / "kems_core" / "agile_historical_replay_cache.py").read_text(
        encoding="utf-8"
    )
    rolling = (CORE / "agile_rolling_replan_runtime.py").read_text(encoding="utf-8")
    coordinator = (CORE / "coordinator.py").read_text(encoding="utf-8")
    assert "if today is None or day >= today or projection:" in source
    assert "runtime.ANALYSIS_REFRESH = timedelta(0)" in rolling
    assert "guard_paid_agile_physical_export(" in coordinator
    assert "apply_verified_happy_hour_preparation(" in coordinator
    assert "self._foxess_control.async_update(" in coordinator
    assert '"day_rate_index_builds"' in (CORE / "diagnostics.py").read_text(
        encoding="utf-8"
    )
