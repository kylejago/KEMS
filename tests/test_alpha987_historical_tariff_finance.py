"""Safe historical tariff and ROI repricing regression tests."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import ModuleType
from zoneinfo import ZoneInfo

from tariff import normalise_october_2026_loyal_options

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"
PACKAGE = "_kems_tariff_repricing_tests"
pkg = ModuleType(PACKAGE)
pkg.__path__ = [str(KEMS)]
sys.modules.setdefault(PACKAGE, pkg)
spec = importlib.util.spec_from_file_location(
    f"{PACKAGE}.historical_tariff_revaluation",
    KEMS / "historical_tariff_revaluation.py",
)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

from kems_core import SimulationConfig, SimulationEngine, Snapshot  # noqa: E402

LONDON = ZoneInfo("Europe/London")


def _source(day: date, rate: float = 37.17) -> list[Snapshot]:
    start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=LONDON)
    return [
        Snapshot(
            timestamp=start + timedelta(minutes=10 * i),
            current_import_rate=rate,
            next_import_rate=6.6,
            house_load_kw=2.0,
            grid_import_kw=2.0,
            grid_export_kw=0.0,
            solar_power_kw=0.0,
            battery_power_kw=0.0,
            battery_soc=50.0,
            ev_power_kw=0.0,
            ev_connected=False,
            off_peak=False,
        )
        for i in range(144)
    ]


def _config() -> SimulationConfig:
    return SimulationConfig(
        export_tariff_status="awaiting",
        battery_export_enabled=False,
        proposal_solar_enabled=False,
    )


def test_corrected_date_default_and_saved_old_default() -> None:
    updated = normalise_october_2026_loyal_options(
        {
            "tariff_change_3_effective_date": "2026-10-12",
            "tariff_change_3_day_rate_pence": 35.88,
            "tariff_change_3_offpeak_rate_pence": 6.60,
            "tariff_change_3_standing_charge_pence": 55.52,
        }
    )
    assert updated["tariff_change_3_effective_date"] == "2026-10-06"
    assert normalise_october_2026_loyal_options(
        {
            "tariff_change_3_effective_date": "2026-10-12",
            "tariff_change_3_day_rate_pence": 25.0,
        }
    )["tariff_change_3_effective_date"] == "2026-10-12"


def test_reprice_readonly_preserves_energy_and_native_provenance() -> None:
    records = _source(date(2026, 10, 6))
    adjusted = mod.financial_replay_records(records)
    assert adjusted[0].current_import_rate == 35.88
    assert records[0].current_import_rate == 37.17
    assert adjusted[0].grid_import_kw == records[0].grid_import_kw
    assert adjusted[0].battery_power_kw == records[0].battery_power_kw


def test_rates_outside_backdate_window_remain_unchanged() -> None:
    assert (
        mod.corrected_2026_import_snapshot(_source(date(2026, 10, 5))[0])
        .current_import_rate
        == 37.17
    )
    assert (
        mod.corrected_2026_import_snapshot(_source(date(2026, 10, 12))[0])
        .current_import_rate
        == 37.17
    )


def test_old_cheap_extra_slot_is_revalued_but_custom_rate_is_preserved() -> None:
    records = _source(date(2026, 10, 7), rate=8.0)
    assert mod.financial_replay_records(records)[0].current_import_rate == 6.6
    assert (
        mod.financial_replay_records(_source(date(2026, 10, 7), rate=11.0))[0]
        .current_import_rate
        == 11.0
    )


def test_daily_financial_replay_and_restart_safety() -> None:
    day = date(2026, 10, 6)
    records = _source(day)
    original = SimulationEngine().simulate_today(
        records, records[-1].timestamp, _config()
    )
    daily = {
        day.isoformat(): {
            "import_cost_pence": original.actual_import_cost_pence,
            mod.PERIOD_DATA_COMPLETE_KEY: 1.0,
        }
    }
    planned, skipped = mod.calculate_2026_tariff_financial_deltas(
        records, daily, _config(), {}
    )
    assert day.isoformat() in planned, skipped
    cost_delta = planned[day.isoformat()]["deltas"]["import_cost_pence"]
    assert cost_delta < 0
    assert planned[day.isoformat()]["deltas"]["simulated_import_cost_pence"] < 0
    assert records[0].current_import_rate == 37.17
    duplicate, _ = mod.calculate_2026_tariff_financial_deltas(
        records, daily, _config(), {day.isoformat(): planned[day.isoformat()]}
    )
    assert not duplicate


def test_missing_daily_record_never_invents_money() -> None:
    proposal, skipped = mod.calculate_2026_tariff_financial_deltas(
        _source(date(2026, 10, 6)), {}, _config(), {}
    )
    assert proposal == {}
    assert skipped["2026-10-06"] == "authoritative daily ledger unavailable"


def test_incomplete_interval_skips_financial_revaluation() -> None:
    day = date(2026, 10, 6)
    records = _source(day)
    # Missing >30 minutes must fail closed, never interpolating monetary value.
    incomplete = records[:30] + records[50:]
    proposal, skipped = mod.calculate_2026_tariff_financial_deltas(
        incomplete,
        {day.isoformat(): {"import_cost_pence": 1000.0}},
        _config(),
        {},
    )
    assert day.isoformat() not in proposal
    assert "missing interval" in skipped[day.isoformat()]
