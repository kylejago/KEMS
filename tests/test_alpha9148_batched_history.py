"""Alpha9.152: historical batches retain chronological SOC and strict invalidation."""

from __future__ import annotations

import ast
import json
from copy import deepcopy
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _batch_method():
    source = (KEMS / "agile_smart_export.py").read_text()
    cls = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.ClassDef) and node.name == "AgileSmartExportManager"
    )
    method = next(
        node
        for node in cls.body
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
    namespace = {}
    exec(
        compile(ast.fix_missing_locations(module), "<historical-batch>", "exec"),
        namespace,
    )
    return namespace["_historical_comparison_batch"]


def test_batched_history_matches_soc_chaining_and_corrected_backfill() -> None:
    batch = _batch_method()
    d1, d2 = date(2026, 10, 21), date(2026, 10, 22)
    days = [
        (d1, [{"energy_kwh": 1.0}]),
        (d2, [{"energy_kwh": 2.0}]),
    ]

    class Manager:
        def __init__(self):
            self.cache = {}
            self.calculations = 0
            self.hits = 0
            self.inputs = []

        def key(self, records, config, tariff, agile_soc, full_soc, learned):
            return (
                records[0]["energy_kwh"],
                config["reserve"],
                tariff["export_rate"],
                agile_soc,
                full_soc,
                learned,
            )

        def _historical_cached_comparison(
            self, records, config, tariff, agile_soc, full_soc, learned, *, today
        ):
            assert today == date(2026, 10, 27)
            assert learned is None
            key = self.key(records, config, tariff, agile_soc, full_soc, learned)
            if key in self.cache:
                self.hits += 1
                return deepcopy(self.cache[key])
            return None

        def _compare_day(self, records, config, tariff, agile_soc, full_soc, learned):
            self.calculations += 1
            self.inputs.append((agile_soc, full_soc))
            result = {
                "ready": True,
                "agile_smart_export": {
                    "ending_soc_percent": agile_soc - records[0]["energy_kwh"]
                },
                "full_kems_forecast": {
                    "ending_soc_percent": full_soc - records[0]["energy_kwh"] / 2
                },
            }
            key = self.key(records, config, tariff, agile_soc, full_soc, learned)
            self.cache[key] = deepcopy(result)
            return result

    obj = Manager()
    config, tariff = {"reserve": 15}, {"export_rate": 20.0}

    def call():
        return batch(
            obj,
            days,
            config,
            tariff,
            90.0,
            85.0,
            date(2026, 10, 27),
        )

    first = call()
    assert list(first) == [d1.isoformat(), d2.isoformat()]
    assert obj.inputs == [(90.0, 85.0), (89.0, 84.5)]
    assert first[d2.isoformat()]["agile_smart_export"]["ending_soc_percent"] == 87.0

    cached = call()
    assert cached == first
    assert obj.calculations == 2
    assert obj.hits == 2

    days[0][1][0]["energy_kwh"] = 3.0
    corrected = call()
    assert obj.calculations == 4
    assert corrected[d2.isoformat()]["agile_smart_export"]["ending_soc_percent"] == 85.0

    tariff["export_rate"] = 25.0
    call()
    assert obj.calculations == 6
    config["reserve"] = 10
    call()
    assert obj.calculations == 8


def test_batched_worker_does_not_replace_live_or_tomorrow_executor() -> None:
    source = (KEMS / "agile_smart_export.py").read_text()
    assert "if day < today_date and len(day_records) >= 2" in source
    assert "batched_results = await executor(" in source
    assert "historical_batch_executor_jobs = 1" in source
    assert '"historical_executor_jobs_total"' in source
    assert "historical_lookup_event_loop_offloaded" in source
    assert "if day < today_date and day.isoformat() in batched_results:" in source
    assert "await executor(self._compare_day, *compare_args)" in source
    assert "tomorrow = await executor(" in source


def test_second_handoff_publication_retains_exact_change_gate() -> None:
    source = (KEMS / "agile_settled_soc_handoff.py").read_text()
    assert '"second_publication_change_reasons"' in source
    assert (
        '("tomorrow_slots", prior_tomorrow_slots != state["tomorrow_slots"])' in source
    )
    assert '"tomorrow_soc_handoff"' in source
    assert '"price_quality"' in source
    assert '"tomorrow_period"' in source
    assert "if second_publication_needed:" in source


def test_alpha9148_manifest_and_safety_scope() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    assert manifest["version"] == "0.9.0-alpha9.152"
    assert bundle["maintenance"]["reason"].startswith("Alpha9.152:")
    coordinator = (KEMS / "coordinator.py").read_text()
    assert "guard_paid_agile_physical_export(" in coordinator
    assert "self._foxess_control.async_update(" in coordinator
    assert "if post_shadow_settlement_changed:" in coordinator
