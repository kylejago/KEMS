"""Alpha9.156: strict whole-batch history validation, with per-day fallback."""

from __future__ import annotations

import ast
from copy import deepcopy
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from pickle import HIGHEST_PROTOCOL, PicklingError, dumps
from runpy import run_path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
HistoricalReplayCache = run_path(
    str(ROOT / "kems_core/agile_historical_replay_cache.py")
)["HistoricalReplayCache"]


def _batch_method():
    source = (ROOT / "agile_smart_export.py").read_text()
    manager = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.ClassDef) and node.name == "AgileSmartExportManager"
    )
    method = next(
        node for node in manager.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_historical_comparison_batch"
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            method,
        ],
        type_ignores=[],
    )
    namespace = {
        "sha256": sha256,
        "dumps": dumps,
        "HIGHEST_PROTOCOL": HIGHEST_PROTOCOL,
        "PicklingError": PicklingError,
    }
    exec(compile(ast.fix_missing_locations(module), "<batch>", "exec"), namespace)
    return namespace["_historical_comparison_batch"]


class Manager:
    def __init__(self, *, now=date(2026, 10, 28)):
        self.today = now
        self._product_code = "AGILE-OUTGOING"
        self._tariff_code = "REGION-L"
        self._historical_replay_cache = HistoricalReplayCache()
        self.rates = {
            date(2026, 10, 24): [{"price": 20.0}],
            date(2026, 10, 25): [{"price": 22.0}],
        }
        self.computations = 0

    def _day_rates(self, day):
        return self.rates.get(day, [])

    def _inputs(self, records, config, tariff, agile_soc, full_soc, learned):
        day = records[0]["timestamp"].date()
        return (
            records, config, tariff, agile_soc, full_soc, learned,
            self._day_rates(day), self._product_code, self._tariff_code,
        )

    def _historical_cached_comparison(
        self, records, config, tariff, agile_soc, full_soc, learned, *, today
    ):
        return self._historical_replay_cache.get_cached(
            day=records[0]["timestamp"].date(),
            today=today,
            projection=False,
            inputs=self._inputs(records, config, tariff, agile_soc, full_soc, learned),
        )

    def _compare_day(self, records, config, tariff, agile_soc, full_soc, learned):
        self.computations += 1
        day = records[0]["timestamp"].date()
        power = records[0]["nested"]["power"]
        result = self._historical_replay_cache.evaluate(
            day=day,
            today=self.today,
            projection=False,
            inputs=self._inputs(records, config, tariff, agile_soc, full_soc, learned),
            calculate=lambda: {
                "ready": True,
                "agile_smart_export": {
                    "ending_soc_percent": agile_soc - power,
                    "net": self.rates[day][0]["price"] + tariff["rate"],
                },
                "full_kems_forecast": {"ending_soc_percent": full_soc - power},
                "slot_plan": [{"power": power}],
            },
        )
        return result


def _days():
    return [
        (day, [
            {"timestamp": datetime(day.year, day.month, day.day, 12),
             "nested": {"power": power}},
            {"timestamp": datetime(day.year, day.month, day.day, 13),
             "nested": {"power": 0.0}},
        ])
        for day, power in (
            (date(2026, 10, 24), 1.0), (date(2026, 10, 25), 2.0)
        )
    ]


def test_batch_signature_skips_per_day_pickle_and_isolates_results():
    manager = Manager()
    batch = _batch_method()
    days = _days()
    config, tariff = {"reserve": 15}, {"rate": 6.6}

    def run():
        return batch(manager, days, config, tariff, 90.0, 85.0, manager.today)

    first = run()
    assert manager.computations == 2
    baseline = manager._historical_replay_cache.status["pickle_fingerprints"]
    assert baseline == 2
    second = run()
    assert first == second
    assert manager.computations == 2
    assert manager._historical_replay_cache.status["pickle_fingerprints"] == baseline
    assert manager._historical_replay_cache.status["verified_batch_hits"] == 1
    assert manager._historical_replay_cache.status["verified_batch_days"] == 2
    second["2026-10-24"]["slot_plan"][0]["power"] = 999.0
    assert run()["2026-10-24"]["slot_plan"][0]["power"] == 1.0


def test_nested_backfill_prices_config_and_carried_soc_invalidate():
    manager = Manager()
    days = _days()
    config, tariff = {"reserve": 15}, {"rate": 6.6}
    batch = _batch_method()

    def run(initial=90.0):
        return batch(manager, days, config, tariff, initial, 85.0, manager.today)

    run()
    run()
    assert manager.computations == 2

    days[0][1][0]["nested"]["power"] = 3.0
    result = run()
    assert manager.computations == 4
    assert result["2026-10-25"]["agile_smart_export"]["ending_soc_percent"] == 85.0
    manager.rates[date(2026, 10, 25)][0]["price"] = 40.0
    assert run()["2026-10-25"]["agile_smart_export"]["net"] == 46.6
    assert manager.computations == 5
    tariff["rate"] = 7.0
    run()
    assert manager.computations == 7
    config["reserve"] = 10
    run()
    assert manager.computations == 9
    run(initial=89.0)
    assert manager.computations == 11


def test_cache_revision_rejects_external_restore_and_new_day():
    manager = Manager()
    days = _days()
    batch = _batch_method()
    params = (days, {"reserve": 15}, {"rate": 6.6}, 90.0, 85.0, manager.today)
    first = batch(manager, *params)
    batch(manager, *params)
    assert manager._historical_replay_cache.status["verified_batch_hits"] == 1
    state = manager._historical_replay_cache.export_state()
    manager._historical_replay_cache.restore_state(state)
    # Same SHA bytes, but a new cache revision: use per-day strict checks.
    assert batch(manager, *params) == first
    assert manager._historical_replay_cache.status["verified_batch_hits"] == 1
    assert batch(manager, *params) == first
    assert manager._historical_replay_cache.status["verified_batch_hits"] == 2
    days.append((
        date(2026, 10, 26),
        [{"timestamp": datetime(2026, 10, 26, 12), "nested": {"power": 2.0}}],
    ))
    assert len(batch(manager, *params)) == 3


def test_dst_fold_and_unpicklable_inputs_fail_closed():
    manager = Manager()
    batch = _batch_method()
    london = ZoneInfo("Europe/London")
    days = _days()
    days[1][1][0]["timestamp"] = datetime(
        2026, 10, 25, 1, 30, tzinfo=london, fold=0
    )
    params = (days, {"reserve": 15}, {"rate": 6.6}, 90.0, 85.0, manager.today)
    batch(manager, *params)
    batch(manager, *params)
    assert manager.computations == 2
    days[1][1][0]["timestamp"] = datetime(
        2026, 10, 25, 1, 30, tzinfo=london, fold=1
    )
    batch(manager, *params)
    assert manager.computations == 3
    # A non-picklable dynamic source is never considered a batch signature.
    days[0][1][0]["nonpickle"] = lambda: 5
    batch(manager, *params)
    previous = manager._historical_replay_cache.status["verified_batch_hits"]
    batch(manager, *params)
    assert manager._historical_replay_cache.status["verified_batch_hits"] == previous


def test_current_and_future_day_still_uncached():
    manager = Manager(now=date(2026, 10, 25))
    batch = _batch_method()
    days = [(date(2026, 10, 25), _days()[1][1])]
    params = (days, {"reserve": 15}, {"rate": 6.6}, 90.0, 85.0, manager.today)
    batch(manager, *params)
    batch(manager, *params)
    assert manager.computations == 2
    assert manager._historical_replay_cache.status["verified_batch_hits"] == 0


def test_no_changed_foxess_ev_or_live_day_authority():
    source = (ROOT / "agile_smart_export.py").read_text()
    coordinator = (ROOT / "coordinator.py").read_text()
    assert "if day < today_date and day.isoformat() in batched_results:" in source
    assert "today = calculated.get(local_now.date().isoformat())" in source
    assert "await self._foxess_control.async_update(" in coordinator
    assert "guard_paid_agile_physical_export(" in coordinator
