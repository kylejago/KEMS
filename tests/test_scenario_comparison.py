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


def test_compare_today_runs_seven_independent_scenarios() -> None:
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
        "kems_forecast",
        "full_island",
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
        if not scenario.financially_comparable:
            assert scenario.saving_vs_no_system_pence == 0.0
            continue
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
        "kems_forecast_cost_pence",
    ):
        assert isinstance(last[key], float)
    assert isinstance(last["island_load_served_percent"], float)
    assert isinstance(last["island_unserved_load_kwh"], float)
    assert isinstance(last["island_soc_percent"], float)
    assert last["island_status"] in {"survived", "shortfall"}


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


def test_today_scenarios_expose_current_power_routing() -> None:
    """Panel/web clients should receive direct current kW routes for every scenario."""
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
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            inverter_limit_kw=7.0,
            export_limit_kw=7.0,
            proposal_solar_enabled=False,
        ),
    )

    today = result.period("today")
    assert today is not None

    no_system = today.scenario("no_system")
    solar_only = today.scenario("solar_only")
    solar_battery = today.scenario("solar_battery")
    no_export = today.scenario("kems_no_export")
    full = today.scenario("kems_full")
    island = today.scenario("full_island")
    assert all(
        item is not None
        for item in (no_system, solar_only, solar_battery, no_export, full, island)
    )

    assert no_system.current_grid_import_kw == 2.0
    assert no_system.current_grid_export_kw == 0.0
    assert no_system.current_solar_power_kw == 0.0

    assert solar_only.current_solar_power_kw == 3.0
    assert solar_only.current_solar_to_home_kw == 2.0
    assert solar_only.current_grid_import_kw == 0.0
    assert solar_only.current_grid_export_kw == 1.0

    assert solar_battery.current_solar_power_kw == 3.0
    assert solar_battery.current_solar_to_home_kw == 2.0
    assert solar_battery.current_solar_to_battery_kw is not None
    assert solar_battery.current_battery_soc_percent is not None

    assert no_export.current_grid_export_kw == 0.0
    assert no_export.current_house_load_kw == 2.0
    assert full.current_house_load_kw == 2.0
    assert full.current_grid_import_kw is not None
    assert full.current_grid_export_kw is not None

    assert island.current_house_load_kw == 2.0
    assert island.current_grid_import_kw == 0.0
    assert island.current_grid_export_kw == 0.0
    assert island.current_solar_power_kw == 3.0
    assert island.current_battery_soc_percent is not None


def test_current_power_attributes_are_preserved_in_period_rollup() -> None:
    """Current power routing must come from the latest day, never be summed."""
    start = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    records = _records(start, count=8) + _records(start + timedelta(days=1), count=9)
    now = records[-1].timestamp
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

    today = result.period("today")
    seven = result.period("7_days")
    assert today is not None and seven is not None
    today_full = today.scenario("kems_full")
    seven_full = seven.scenario("kems_full")
    assert today_full is not None and seven_full is not None
    assert seven_full.current_grid_import_kw == today_full.current_grid_import_kw
    assert seven_full.current_grid_export_kw == today_full.current_grid_export_kw


def test_full_kems_current_flow_survives_early_day_not_ready_state() -> None:
    """Keep Full-KEMS current routing available during the first daily samples."""
    start = datetime(2026, 8, 12, 0, 0, tzinfo=UTC)
    records = _records(start, count=2)
    result = ScenarioComparisonEngine().compare(
        records,
        records[-1].timestamp,
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=20.0,
            battery_reserve_percent=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            inverter_limit_kw=7.0,
            export_limit_kw=7.0,
            export_rate_pence=12.0,
            proposal_solar_enabled=False,
        ),
    )

    today = result.period("today")
    assert today is not None
    full = today.scenario("kems_full")
    assert full is not None
    assert full.ready is False
    assert full.current_house_load_kw == 2.0
    assert full.current_grid_import_kw is not None
    assert full.current_grid_to_battery_kw is not None


def test_full_island_mode_has_no_grid_and_is_not_a_cost_scenario() -> None:
    """Island replay must model resilience rather than pretend zero grid cost wins."""
    start = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    records = _records(start, count=17)
    result = ScenarioComparisonEngine().compare(
        records,
        records[-1].timestamp,
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=80.0,
            battery_reserve_percent=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            inverter_limit_kw=7.0,
            eps_output_limit_kw=7.0,
            export_limit_kw=7.0,
            proposal_solar_enabled=False,
        ),
    )

    today = result.period("today")
    assert today is not None
    island = today.scenario("full_island")
    assert island is not None and island.ready
    assert island.financially_comparable is False
    assert island.grid_available is False
    assert island.grid_import_kwh == 0.0
    assert island.grid_export_kwh == 0.0
    assert island.battery_grid_charge_kwh == 0.0
    assert island.solar_export_kwh == 0.0
    assert island.total_cost_pence == 0.0
    assert (
        island.load_served_kwh + island.unserved_load_kwh
        == island.house_consumption_kwh
    )
    assert today.cheapest is not None
    assert today.cheapest.key != "full_island"


def test_full_island_reports_eps_shortfall_and_first_failure() -> None:
    """Whole-house demand above EPS capability must become explicit unserved load."""
    start = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start + timedelta(minutes=15 * index),
            current_import_rate=28.3036,
            electricity_standing_charge=53.70435,
            house_load_kw=9.0,
            grid_import_kw=9.0,
            solar_power_kw=0.0,
        )
        for index in range(9)
    ]
    result = ScenarioComparisonEngine().compare(
        records,
        records[-1].timestamp,
        SimulationConfig(
            battery_capacity_kwh=20.0,
            battery_initial_percent=100.0,
            battery_reserve_percent=10.0,
            max_discharge_kw=7.0,
            eps_output_limit_kw=7.0,
            proposal_solar_enabled=False,
        ),
    )

    island = result.scenario("full_island")
    assert island is not None and island.ready
    assert island.outage_survived is False
    assert island.outage_status == "shortfall"
    assert island.load_served_percent < 100.0
    assert island.unserved_load_kwh > 0.0
    assert island.eps_limited_unserved_kwh > 0.0
    assert island.first_shortfall_at is not None


def test_full_island_starts_today_from_previous_full_kems_soc() -> None:
    """A midnight outage should inherit the SOC Full KEMS had at outage start."""
    first = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    records = _records(first, count=9) + _records(first + timedelta(days=1), count=9)
    now = first + timedelta(days=1, hours=2)
    result = ScenarioComparisonEngine().compare(
        records,
        now,
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=50.0,
            battery_reserve_percent=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            proposal_solar_enabled=False,
        ),
    )

    yesterday = result.period("yesterday")
    today = result.period("today")
    assert yesterday is not None and today is not None
    previous_full = yesterday.scenario("kems_full")
    island = today.scenario("full_island")
    assert previous_full is not None and previous_full.ending_soc_percent is not None
    assert island is not None and island.starting_soc_percent is not None
    assert island.starting_soc_percent == previous_full.ending_soc_percent


def test_prepared_island_calculates_required_soc_and_survives_energy_shortfall() -> (
    None
):
    """Advance notice should turn a low-SOC sudden failure into a prepared survival."""
    start = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start + timedelta(minutes=30 * index),
            current_import_rate=28.3036,
            electricity_standing_charge=53.70435,
            house_load_kw=1.0,
            grid_import_kw=1.0,
            solar_power_kw=0.0,
        )
        for index in range(13)
    ]
    result = ScenarioComparisonEngine().compare(
        records,
        records[-1].timestamp,
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=10.0,
            battery_reserve_percent=10.0,
            island_reserve_percent=20.0,
            max_discharge_kw=7.0,
            eps_output_limit_kw=7.0,
            proposal_solar_enabled=False,
        ),
    )

    island = result.scenario("full_island")
    assert island is not None and island.ready
    assert island.outage_survived is False
    assert island.required_starting_soc_status == "ready"
    assert island.required_starting_soc_percent is not None
    assert island.recommended_prepared_soc_percent is not None
    assert (
        island.recommended_prepared_soc_percent >= island.required_starting_soc_percent
    )
    assert island.prepared_outage_survived is True
    assert island.prepared_outage_status == "survived"
    assert island.prepared_load_served_percent == 100.0
    assert island.prepared_unserved_load_kwh == 0.0


def test_prepared_island_separates_eps_limit_from_energy_security() -> None:
    """More battery cannot remove a whole-house load spike above the EPS rating."""
    start = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start + timedelta(minutes=15 * index),
            current_import_rate=28.3036,
            electricity_standing_charge=53.70435,
            house_load_kw=9.0,
            grid_import_kw=9.0,
            solar_power_kw=0.0,
        )
        for index in range(9)
    ]
    result = ScenarioComparisonEngine().compare(
        records,
        records[-1].timestamp,
        SimulationConfig(
            battery_capacity_kwh=20.0,
            battery_initial_percent=10.0,
            battery_reserve_percent=10.0,
            island_reserve_percent=20.0,
            max_discharge_kw=7.0,
            eps_output_limit_kw=7.0,
            proposal_solar_enabled=False,
        ),
    )

    island = result.scenario("full_island")
    assert island is not None and island.ready
    assert island.required_starting_soc_status == "eps_limit_only"
    assert island.required_starting_soc_percent is not None
    assert island.prepared_outage_survived is False
    assert island.prepared_outage_status == "eps_limited"
    assert island.prepared_energy_limited_unserved_kwh == 0.0
    assert island.prepared_eps_limited_unserved_kwh > 0.0


def test_prepared_island_reports_when_100_percent_still_lacks_energy() -> None:
    """Required SOC must not claim success when even a full battery is insufficient."""
    start = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start + timedelta(hours=index),
            current_import_rate=28.3036,
            electricity_standing_charge=53.70435,
            house_load_kw=2.0,
            grid_import_kw=2.0,
            solar_power_kw=0.0,
        )
        for index in range(13)
    ]
    result = ScenarioComparisonEngine().compare(
        records,
        records[-1].timestamp,
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=10.0,
            battery_reserve_percent=10.0,
            island_reserve_percent=20.0,
            max_discharge_kw=7.0,
            eps_output_limit_kw=7.0,
            proposal_solar_enabled=False,
        ),
    )

    island = result.scenario("full_island")
    assert island is not None and island.ready
    assert island.required_starting_soc_percent is None
    assert island.required_starting_soc_status == "insufficient_energy_even_at_100"
    assert island.recommended_prepared_soc_percent == 100.0
    assert island.prepared_starting_soc_percent == 100.0
    assert island.prepared_outage_survived is False
    assert island.prepared_outage_status == "shortfall"
    assert island.prepared_energy_limited_unserved_kwh > 0.0


def test_current_flow_uses_live_snapshot_between_history_samples() -> None:
    """Current routes should not wait for the five-minute history interval."""
    start = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    records = _records(start)
    records[-1].stale_fields = ("house_load_kw",)
    current = Snapshot(
        timestamp=records[-1].timestamp + timedelta(minutes=1),
        current_import_rate=28.3036,
        electricity_standing_charge=53.70435,
        off_peak=False,
        house_load_kw=4.0,
        grid_import_kw=4.0,
        grid_export_kw=0.0,
        solar_power_kw=1.0,
        next_offpeak_start=start + timedelta(days=1),
    )
    result = ScenarioComparisonEngine().compare(
        records,
        current.timestamp,
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=50.0,
            battery_reserve_percent=10.0,
            export_rate_pence=12.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            inverter_limit_kw=7.0,
            eps_output_limit_kw=7.0,
            export_limit_kw=7.0,
            proposal_solar_enabled=False,
        ),
        current_snapshot=current,
    )

    today = result.period("today")
    assert today is not None
    no_system = today.scenario("no_system")
    solar_only = today.scenario("solar_only")
    full = today.scenario("kems_full")
    island = today.scenario("full_island")
    assert no_system is not None
    assert solar_only is not None
    assert full is not None
    assert island is not None

    assert no_system.samples == len(records)
    assert no_system.current_house_load_kw == 4.0
    assert no_system.current_grid_import_kw == 4.0
    assert solar_only.current_solar_power_kw == 1.0
    assert full.current_house_load_kw == 4.0
    assert full.current_grid_import_kw is not None
    assert island.current_house_load_kw == 4.0
    assert island.current_grid_import_kw == 0.0
    assert island.current_grid_export_kw == 0.0


def test_island_mode_sheds_ev_before_eps_and_shortfall_accounting() -> None:
    """EV charging is intentional load shedding, not an island-mode failure."""
    start = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start + timedelta(minutes=15 * index),
            current_import_rate=3.4933,
            electricity_standing_charge=53.70435,
            off_peak=True,
            house_load_kw=8.0,
            grid_import_kw=8.0,
            grid_export_kw=0.0,
            solar_power_kw=0.0,
            ev_connected=True,
            ev_charging=True,
            ev_power_kw=7.0,
        )
        for index in range(9)
    ]
    result = ScenarioComparisonEngine().compare(
        records,
        records[-1].timestamp,
        SimulationConfig(
            battery_capacity_kwh=20.0,
            battery_initial_percent=100.0,
            battery_reserve_percent=10.0,
            island_reserve_percent=20.0,
            max_discharge_kw=7.0,
            eps_output_limit_kw=7.0,
            proposal_solar_enabled=False,
        ),
        current_snapshot=records[-1],
    )

    island = result.scenario("full_island")
    assert island is not None and island.ready
    assert island.house_consumption_kwh == 16.0
    assert island.ev_energy_intentionally_shed_kwh == 14.0
    assert island.island_demand_kwh == 2.0
    assert island.ev_charging_allowed_in_island is False
    assert island.load_served_kwh == 2.0
    assert island.unserved_load_kwh == 0.0
    assert island.eps_limited_unserved_kwh == 0.0
    assert island.energy_limited_unserved_kwh == 0.0
    assert island.load_served_percent == 100.0
    assert island.outage_survived is True
    assert island.required_starting_soc_status == "ready"
    assert island.prepared_outage_status == "survived"
    assert island.current_house_load_kw == 1.0
    assert island.current_ev_shed_kw == 7.0


def test_full_kems_forecast_matches_full_kems_without_recorded_forecast() -> None:
    """Historical data from before alpha7 must not be rewritten by today's forecast."""
    start = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    result = ScenarioComparisonEngine().compare(
        _records(start, count=13),
        start + timedelta(hours=3),
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=80.0,
            battery_reserve_percent=10.0,
            export_rate_pence=12.0,
            proposal_solar_enabled=False,
        ),
    )
    today = result.period("today")
    assert today is not None
    full = today.scenario("kems_full")
    forecast = today.scenario("kems_forecast")
    assert full is not None and forecast is not None
    assert forecast.total_cost_pence == full.total_cost_pence
    assert forecast.grid_import_kwh == full.grid_import_kwh
    assert forecast.grid_export_kwh == full.grid_export_kwh
    assert forecast.forecast_samples == 0


def test_full_kems_forecast_uses_solar_recovery_only_in_new_scenario() -> None:
    """Forecast recovery may store PV while ordinary Full KEMS remains unchanged."""
    start = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    records = []
    for index in range(3):
        records.append(
            Snapshot(
                timestamp=start + timedelta(minutes=15 * index),
                current_import_rate=28.3036,
                electricity_standing_charge=53.7,
                off_peak=False,
                house_load_kw=2.0,
                grid_import_kw=2.0,
                solar_power_kw=6.0,
                next_offpeak_start=start + timedelta(hours=11, minutes=30),
                forecast_protection_state="recovery",
                forecast_solar_recovery_target_percent=90.0,
                forecast_minimum_precheap_soc_percent=10.0,
                forecast_required_morning_soc_percent=80.0,
                forecast_recharge_target_feasible=True,
                forecast_recharge_shortfall_kwh=0.0,
            )
        )
    result = ScenarioComparisonEngine().compare(
        records,
        records[-1].timestamp,
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=50.0,
            battery_reserve_percent=10.0,
            export_rate_pence=12.0,
            export_tariff_status="active",
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            inverter_limit_kw=7.0,
            export_limit_kw=7.0,
            proposal_solar_enabled=False,
        ),
        current_snapshot=records[-1],
    )
    today = result.period("today")
    assert today is not None
    full = today.scenario("kems_full")
    forecast = today.scenario("kems_forecast")
    assert full is not None and forecast is not None
    assert forecast.forecast_samples == 3
    assert forecast.forecast_protection_state == "recovery"
    assert (forecast.current_solar_to_battery_kw or 0.0) > 0.0
    assert (forecast.current_solar_to_home_kw or 0.0) > 0.0
    assert (full.current_solar_to_battery_kw or 0.0) == 0.0
