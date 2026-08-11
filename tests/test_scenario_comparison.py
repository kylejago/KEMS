"""Tests for parallel KEMS what-if scenario comparison."""

from datetime import UTC, datetime, timedelta

from kems_core import ScenarioComparisonEngine, SimulationConfig, Snapshot


def _records(start: datetime, count: int = 9) -> list[Snapshot]:
    records: list[Snapshot] = []
    for index in range(count):
        timestamp = start + timedelta(minutes=15 * index)
        cheap = timestamp.hour < 1
        records.append(
            Snapshot(
                timestamp=timestamp,
                current_import_rate=3.4933 if cheap else 28.3036,
                electricity_standing_charge=53.70435,
                off_peak=cheap,
                house_load_kw=2.0,
                grid_import_kw=2.0,
                grid_export_kw=0.0,
                solar_power_kw=3.0 if timestamp.hour >= 1 else 0.0,
                next_offpeak_start=start + timedelta(days=1),
            )
        )
    return records


def test_compare_today_runs_five_independent_scenarios() -> None:
    """Changing the live export setting must not disable hypothetical replays."""
    start = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    records = _records(start)
    result = ScenarioComparisonEngine().compare(
        records,
        records[-1].timestamp,
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=50.0,
            battery_reserve_percent=10.0,
            export_rate_pence=12.0,
            export_tariff_status="awaiting",
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            inverter_limit_kw=7.0,
            export_limit_kw=7.0,
            proposal_solar_enabled=False,
        ),
    )

    today = result.period("today")
    assert today is not None
    assert [item.key for item in today.scenarios] == [
        "no_system",
        "solar_only",
        "solar_battery",
        "kems_no_export",
        "kems_full",
    ]
    no_export = today.scenario("kems_no_export")
    full = today.scenario("kems_full")
    assert no_export is not None and full is not None
    assert no_export.grid_export_kwh == 0.0
    assert no_export.export_income_pence == 0.0
    assert 0.0 <= no_export.data_coverage <= 100.0
    assert 0.0 <= full.data_coverage <= 100.0
    # Full KEMS is always replayed with the paid export tariff even when the
    # currently selected live-readiness setting is awaiting export.
    assert full.export_income_pence >= 0.0
    assert full.total_cost_pence != no_export.total_cost_pence


def test_cost_saving_breakdown_reconciles_exactly() -> None:
    """The explainable saving components should reconcile to total saving."""
    start = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    result = ScenarioComparisonEngine().compare(
        _records(start),
        start + timedelta(hours=2),
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=50.0,
            battery_reserve_percent=10.0,
            export_rate_pence=12.0,
            proposal_solar_enabled=False,
        ),
    )
    today = result.period("today")
    assert today is not None
    baseline = today.scenario("no_system")
    assert baseline is not None

    for scenario in today.scenarios:
        expected = (
            scenario.day_rate_import_reduction_pence
            + scenario.cheap_rate_import_change_pence
            + scenario.export_income_pence
            + scenario.power_down_income_pence
        )
        assert abs(expected - scenario.saving_vs_no_system_pence) <= 0.02
        assert (
            abs(
                baseline.total_cost_pence
                - scenario.total_cost_pence
                - scenario.saving_vs_no_system_pence
            )
            <= 0.02
        )


def test_today_timeline_contains_all_scenario_cost_lines() -> None:
    """The web/ApexCharts payload should replay cumulative costs from midnight."""
    start = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    records = _records(start, count=13)
    result = ScenarioComparisonEngine().compare(
        records,
        records[-1].timestamp,
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=50.0,
            battery_reserve_percent=10.0,
            export_rate_pence=12.0,
            proposal_solar_enabled=False,
        ),
    )

    assert 2 <= len(result.timeline) <= 49
    last = result.timeline[-1].to_dict()
    assert last["timestamp"].startswith("2026-08-11T")
    for key in (
        "no_system_cost_pence",
        "solar_only_cost_pence",
        "solar_battery_cost_pence",
        "kems_no_export_cost_pence",
        "kems_full_cost_pence",
    ):
        assert isinstance(last[key], float)


def test_period_rollups_include_yesterday_and_seven_days() -> None:
    """Historical comparison data should aggregate without rewriting observations."""
    start = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    records = _records(start, count=8) + _records(start + timedelta(days=1), count=8)
    now = start + timedelta(days=1, hours=2)
    result = ScenarioComparisonEngine().compare(
        records,
        now,
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=50.0,
            battery_reserve_percent=10.0,
            proposal_solar_enabled=False,
        ),
    )

    yesterday = result.period("yesterday")
    seven = result.period("7_days")
    assert yesterday is not None and yesterday.days_included == 1
    assert seven is not None and seven.days_included == 2
    assert seven.scenario("no_system") is not None
    assert seven.scenario("no_system").total_cost_pence > 0
