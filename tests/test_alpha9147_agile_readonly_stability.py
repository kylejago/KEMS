"""Alpha9.148: historical cache is off-loop; redundant handoff publish is gated."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from time import perf_counter, thread_time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def test_only_historical_exact_cache_checks_move_to_executor() -> None:
    source = (KEMS / "agile_smart_export.py").read_text()
    assert "if day < local_now.date() and callable(executor):" in source
    assert "cached_result = await executor(" in source
    assert "historical_lookup, *compare_args, today=local_now.date()" in source
    assert '"historical_lookup_executor_jobs"' in source
    # Changed histories still evaluate by the original numerical path;
    # today's replay and tomorrow projection are not served from this cache.
    assert "await executor(self._compare_day, *compare_args)" in source
    assert "tomorrow = await executor(" in source
    assert "result = self._compare_day(*compare_args)" in source


def _handoff_function():
    """Extract the pure helper without importing Home Assistant."""
    source = (KEMS / "agile_settled_soc_handoff.py").read_text()
    method = next(
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef)
        and node.name == "refresh_tomorrow_handoff_from_settled_soc"
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

    class LearnedState:
        pass

    class SolarForecastState:
        pass

    class ForecastPlanState:
        def __init__(self):
            self.projected_soc_at_cheap_start_percent = 74.0

    class TariffSettings:
        offpeak_start = time(23, 30)
        offpeak_end = time(5, 30)

    def _number(value):
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def _aggregate(results, key, label):
        return {
            "ready": True,
            "days_included": len(results),
            "agile_smart_export": {"ending_soc_percent": 80.0},
            "full_kems_forecast": {"ending_soc_percent": 82.0},
            "comparison": {"winner": "same"},
        }

    ns = {
        "datetime": datetime,
        "perf_counter": perf_counter,
        "thread_time": thread_time,
        "timedelta": timedelta,
        "LONDON": ZoneInfo("Europe/London"),
        "LearnedState": LearnedState,
        "SolarForecastState": SolarForecastState,
        "ForecastPlanState": ForecastPlanState,
        "TariffSettings": TariffSettings,
        "_number": _number,
        "agile": SimpleNamespace(
            LONDON=ZoneInfo("Europe/London"),
            _aggregate=_aggregate,
            _quality=lambda *args: {"today_count": 48},
        ),
        "reconcile_precheap_projection": lambda **kw: (
            kw["projected_precheap_soc_percent"],
            {
                "soc_authority": "test",
                "projected_precheap_soc_percent": kw["projected_precheap_soc_percent"],
            },
        ),
        "project_tomorrow_midnight_soc": lambda **kw: (
            kw["current_soc_percent"],
            {"active": True},
        ),
        "_today_display_midnight_soc": lambda *args, **kwargs: None,
    }
    exec(compile(ast.fix_missing_locations(module), "<handoff>", "exec"), ns)
    return (
        ns["refresh_tomorrow_handoff_from_settled_soc"],
        LearnedState,
        SolarForecastState,
        ForecastPlanState,
        TariffSettings,
    )


def test_second_handoff_publication_skips_only_identical_tomorrow() -> None:
    fn, Learned, Solar, Forecast, Tariff = _handoff_function()
    manager = SimpleNamespace(
        _state={
            "periods": {
                "today": {
                    "agile_smart_export": {"ending_soc_percent": 80},
                    "full_kems_forecast": {"ending_soc_percent": 82},
                },
                "tomorrow": {},
            },
            "rolling_export_plan": {"simulated_soc_percent": 75.0},
            "price_quality": {},
            "today_slots": [],
        },
        _kems_forecast_arbitrage_learned=Learned(),
        _kems_forecast_arbitrage_forecast=Solar(),
        _kems_forecast_arbitrage_plan=Forecast(),
        _rolling_tariff=Tariff(),
        _tomorrow_records=lambda *args: [1, 2],
        _compare_day=lambda *args, **kwargs: {"ready": True},
        _slot_payload=lambda *args: [{"slot": "tomorrow"}],
    )
    publications = []
    manager._publish = lambda state: publications.append(dict(state))
    config = SimpleNamespace(
        battery_initial_percent=70,
        battery_reserve_percent=15,
        battery_capacity_kwh=56.42,
        max_charge_kw=7,
        discharge_efficiency=0.95,
        charge_efficiency=0.95,
    )
    now = datetime(2026, 10, 27, 8, 15, tzinfo=UTC)

    first = fn(manager, now=now, config=config)
    assert first["applied"] is True
    assert first["second_publication_needed"] is True
    assert len(publications) == 1

    second = fn(manager, now=now, config=config)
    assert second["unchanged_tomorrow_publication_skipped"] is True
    assert len(publications) == 1

    # Any changed Tomorrow slot still republishes during this same scan.
    manager._slot_payload = lambda *args: [{"slot": "corrected-price"}]
    corrected = fn(manager, now=now, config=config)
    assert corrected["second_publication_needed"] is True
    assert len(publications) == 2

    # A new cheap-period SOC forecast also invalidates the skip gate.
    manager._kems_forecast_arbitrage_plan.projected_soc_at_cheap_start_percent = 73
    changed_forecast = fn(manager, now=now, config=config)
    assert changed_forecast["second_publication_needed"] is True
    assert len(publications) == 3


def test_release_scope_preserves_control_safety() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())
    assert manifest["version"] == "0.9.0-alpha9.165"
    assert "Alpha9.147" in bundle["maintenance"]["reason"]
    coordinator = (KEMS / "coordinator.py").read_text()
    assert "guard_paid_agile_physical_export(" in coordinator
    assert "self._foxess_control.async_update(" in coordinator
    assert "if post_shadow_settlement_changed:" in coordinator
