"""Tests for the KEMS read-only simulation engine."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from kems_core import SimulationConfig, SimulationEngine, Snapshot


def test_battery_arbitrage_can_reduce_day_import() -> None:
    """Cheap charging followed by day discharge should reduce day-rate import."""
    start = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start,
            current_import_rate=3.49,
            off_peak=True,
            house_load_kw=1.0,
            grid_import_kw=1.0,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=15),
            current_import_rate=28.3,
            off_peak=False,
            house_load_kw=2.0,
            grid_import_kw=2.0,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=30),
            current_import_rate=28.3,
            off_peak=False,
            house_load_kw=2.0,
            grid_import_kw=2.0,
        ),
    ]

    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(minutes=31),
        SimulationConfig(
            battery_capacity_kwh=10,
            battery_initial_percent=10,
            battery_reserve_percent=10,
            max_charge_kw=5,
            max_discharge_kw=5,
            export_rate_pence=0,
            proposal_solar_enabled=False,
            battery_export_enabled=False,
        ),
    )

    assert result.ready is False  # only two priced intervals are complete
    assert result.simulated_grid_import_kwh is not None
    assert result.actual_grid_import_kwh is not None
    assert result.saving_pence is not None and result.saving_pence > 0
    assert (
        result.avoided_day_rate_import_kwh is not None
        and result.avoided_day_rate_import_kwh > 0
    )


def test_proposal_solar_and_fixed_export_rate_are_accounted_for() -> None:
    """The simulation should expose solar export and 12p export income."""
    start = datetime(2026, 7, 31, 11, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start,
            current_import_rate=28.3,
            house_load_kw=1.0,
            grid_import_kw=1.0,
            off_peak=False,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=15),
            current_import_rate=28.3,
            house_load_kw=1.0,
            grid_import_kw=1.0,
            off_peak=False,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=30),
            current_import_rate=28.3,
            house_load_kw=1.0,
            grid_import_kw=1.0,
            off_peak=False,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=45),
            current_import_rate=28.3,
            house_load_kw=1.0,
            grid_import_kw=1.0,
            off_peak=False,
        ),
    ]

    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(hours=1),
        SimulationConfig(
            export_rate_pence=12.0,
            proposal_solar_enabled=True,
            battery_export_enabled=False,
        ),
        forecast_energy_until_offpeak_kwh=10.0,
    )

    assert result.ready is True
    assert result.simulated_solar_generation_kwh is not None
    assert result.simulated_solar_generation_kwh > 0
    assert result.simulated_grid_export_kwh is not None
    assert result.simulated_grid_export_kwh > 0
    assert result.simulated_export_income_pence is not None
    assert result.simulated_export_income_pence > 0
    assert result.actual_grid_export_kwh == 0.0
    assert result.actual_export_income_pence == 0.0
    assert result.effective_export_rate_pence == 12.0


def test_fixed_export_rate_ignores_live_flux_rate() -> None:
    """The proposal simulation must remain on Kyle's fixed 12p export rate."""
    start = datetime(2026, 7, 31, 11, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start,
            current_import_rate=28.3,
            current_export_rate=15.0,
            house_load_kw=0.5,
            grid_import_kw=0.5,
            off_peak=False,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=15),
            current_import_rate=28.3,
            current_export_rate=15.0,
            house_load_kw=0.5,
            grid_import_kw=0.5,
            off_peak=False,
        ),
    ]

    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(minutes=16),
        SimulationConfig(
            export_rate_pence=12.0,
            proposal_solar_enabled=True,
            battery_export_enabled=False,
        ),
    )

    assert result.effective_export_rate_pence == 12.0


def test_simulation_exposes_system_value_and_live_energy_totals() -> None:
    """ROI inputs should separate avoided import, export, solar, EV, and battery."""
    start = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start,
            current_import_rate=30.0,
            current_export_rate=12.0,
            house_load_kw=2.0,
            ev_power_kw=1.0,
            solar_power_kw=3.0,
            battery_power_kw=1.0,
            grid_import_kw=0.0,
            grid_export_kw=1.0,
            off_peak=False,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=30),
            current_import_rate=30.0,
            current_export_rate=12.0,
            house_load_kw=2.0,
            ev_power_kw=0.0,
            solar_power_kw=3.0,
            battery_power_kw=0.0,
            grid_import_kw=0.0,
            grid_export_kw=1.0,
            off_peak=False,
        ),
    ]

    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(minutes=31),
        SimulationConfig(
            proposal_solar_enabled=False,
            battery_export_enabled=False,
            battery_power_positive_is_discharge=True,
        ),
    )

    assert result.actual_house_consumption_kwh == 1.0
    assert result.actual_ev_energy_kwh == 0.5
    assert result.actual_solar_generation_kwh == 1.5
    assert result.actual_battery_discharge_kwh == 0.5
    assert result.baseline_no_system_cost_pence == 30.0
    assert result.actual_export_income_pence == 6.0
    assert result.actual_avoided_import_value_pence == 30.0
    assert result.actual_system_value_pence == 36.0


def test_paced_export_spreads_surplus_across_remaining_hours() -> None:
    """Battery export should be paced instead of dumped after cheap charging."""
    start = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)
    cheap_start = start + timedelta(hours=10)
    records = [
        Snapshot(
            timestamp=start + timedelta(minutes=30 * index),
            current_import_rate=28.3,
            house_load_kw=0.0,
            grid_import_kw=0.0,
            off_peak=False,
            next_offpeak_start=cheap_start,
        )
        for index in range(3)
    ]

    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(hours=1),
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=100.0,
            battery_reserve_percent=10.0,
            max_charge_kw=7.0,
            max_discharge_kw=7.0,
            inverter_limit_kw=7.0,
            export_limit_kw=7.0,
            proposal_solar_enabled=False,
            strategy="paced_export",
        ),
        forecast_energy_until_offpeak_kwh=2.0,
        current_snapshot=records[-1],
    )

    assert result.simulated_battery_export_kwh is not None
    assert result.simulated_battery_export_kwh < 1.0
    assert result.target_battery_export_power_kw is not None
    assert 0.4 < result.target_battery_export_power_kw < 1.0
    assert result.simulated_battery_soc is not None
    assert result.simulated_battery_soc > 90.0
    assert result.projected_soc_at_cheap_period_percent == 10.0


def test_combined_solar_and_battery_output_respects_kh7_limit() -> None:
    """Solar plus battery AC output must never exceed the KH7 7kW limit."""
    start = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    cheap_start = start + timedelta(hours=10)
    records = [
        Snapshot(
            timestamp=start,
            current_import_rate=28.3,
            house_load_kw=2.0,
            grid_import_kw=2.0,
            solar_power_kw=6.0,
            off_peak=False,
            next_offpeak_start=cheap_start,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=5),
            current_import_rate=28.3,
            house_load_kw=2.0,
            grid_import_kw=2.0,
            solar_power_kw=6.0,
            off_peak=False,
            next_offpeak_start=cheap_start,
        ),
    ]

    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(minutes=5),
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=100.0,
            battery_reserve_percent=10.0,
            max_discharge_kw=7.0,
            inverter_limit_kw=7.0,
            export_limit_kw=7.0,
            proposal_solar_enabled=False,
            strategy="paced_export",
        ),
        forecast_energy_until_offpeak_kwh=0.0,
        current_snapshot=records[-1],
    )

    assert result.current_simulated_battery_power_kw == 2.0
    assert result.current_simulated_battery_to_home_power_kw == 2.0
    assert result.current_simulated_battery_export_power_kw == 0.0
    assert result.current_simulated_grid_export_kw == 5.0
    assert (
        result.current_simulated_battery_power_kw
        + result.current_simulated_grid_export_kw
        <= 7.0
    )


def test_live_plan_uses_current_snapshot_not_stale_history_sample() -> None:
    """The comparison dashboard should show the current observed house load."""
    start = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start,
            current_import_rate=28.3,
            house_load_kw=0.5,
            grid_import_kw=0.5,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=5),
            current_import_rate=28.3,
            house_load_kw=0.5,
            grid_import_kw=0.5,
        ),
    ]
    live = Snapshot(
        timestamp=start + timedelta(minutes=6),
        current_import_rate=28.3,
        house_load_kw=2.5,
        grid_import_kw=2.5,
    )

    result = SimulationEngine().simulate_today(
        records,
        live.timestamp,
        SimulationConfig(proposal_solar_enabled=False),
        current_snapshot=live,
    )

    assert result.current_simulated_house_load_kw == 2.5


def test_charge_before_midnight_carries_into_new_day_soc() -> None:
    """The 23:30-00:00 charge must not be lost at the calendar-day reset."""
    previous = datetime(2026, 8, 2, 22, 30, tzinfo=UTC)
    midnight = datetime(2026, 8, 3, 0, 0, tzinfo=UTC)
    records: list[Snapshot] = []
    cursor = previous
    while cursor <= midnight + timedelta(minutes=10):
        records.append(
            Snapshot(
                timestamp=cursor,
                current_import_rate=3.4933,
                off_peak=True,
                house_load_kw=1.0,
                grid_import_kw=1.0,
            )
        )
        cursor += timedelta(minutes=5)

    result = SimulationEngine().simulate_today(
        records,
        midnight + timedelta(minutes=10),
        SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_initial_percent=10.0,
            battery_reserve_percent=10.0,
            max_charge_kw=7.0,
            max_discharge_kw=7.0,
            inverter_limit_kw=7.0,
            export_limit_kw=7.0,
            proposal_solar_enabled=False,
        ),
        current_snapshot=records[-1],
    )

    # Ninety minutes of pre-midnight charging plus ten minutes after midnight
    # must be reflected in SOC, while today's charge counter includes only the
    # post-midnight intervals.
    assert result.simulated_battery_soc is not None
    assert result.simulated_battery_soc > 28.0
    assert result.simulated_battery_charge_kwh is not None
    assert result.simulated_battery_charge_kwh < 2.0


def test_kh7_six_hour_cheap_window_does_not_assume_full_charge() -> None:
    """A KH7 cannot lift 56.42kWh from 10% to 100% in six hours at 7kW."""
    local = ZoneInfo("Europe/London")
    cheap_start = datetime(2026, 8, 3, 23, 30, tzinfo=local)
    cheap_end = datetime(2026, 8, 4, 5, 30, tzinfo=local)
    records: list[Snapshot] = []
    cursor = cheap_start
    while cursor <= cheap_end:
        records.append(
            Snapshot(
                timestamp=cursor,
                current_import_rate=3.4933,
                off_peak=cursor < cheap_end,
                house_load_kw=1.0,
                grid_import_kw=1.0,
            )
        )
        cursor += timedelta(minutes=5)

    result = SimulationEngine().simulate_today(
        records,
        cheap_end + timedelta(minutes=1),
        SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_initial_percent=10.0,
            battery_reserve_percent=10.0,
            max_charge_kw=7.0,
            max_discharge_kw=7.0,
            inverter_limit_kw=7.0,
            export_limit_kw=7.0,
            charge_efficiency=0.95,
            proposal_solar_enabled=False,
        ),
        current_snapshot=records[-1],
    )

    # Six hours at 7kW and 95% efficiency stores 39.9kWh. Added to the
    # 5.642kWh held at the 10% reserve, this reaches roughly 80.7% SOC.
    assert result.simulated_battery_soc is not None
    assert 80.6 <= result.simulated_battery_soc <= 80.8
    assert result.simulated_battery_charge_kwh is not None
    # Today's counter begins at local midnight, so the 23:30-00:00 portion is
    # represented in starting SOC rather than counted again today.
    assert 36.4 <= result.simulated_battery_charge_kwh <= 36.7


def test_missing_learning_forecast_reserves_recent_load_and_pauses_export() -> None:
    """A missing forecast must never be treated as zero home demand."""
    start = datetime(2026, 8, 3, 21, 10, tzinfo=UTC)
    cheap_start = datetime(2026, 8, 3, 22, 30, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start,
            current_import_rate=28.3036,
            house_load_kw=1.404,
            grid_import_kw=1.404,
            battery_soc=12.8,
            off_peak=False,
            next_offpeak_start=cheap_start,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=5),
            current_import_rate=28.3036,
            house_load_kw=1.404,
            grid_import_kw=1.404,
            off_peak=False,
            next_offpeak_start=cheap_start,
        ),
    ]

    result = SimulationEngine().simulate_today(
        records,
        records[-1].timestamp,
        SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_initial_percent=10.0,
            battery_reserve_percent=10.0,
            max_charge_kw=7.0,
            max_discharge_kw=7.0,
            inverter_limit_kw=7.0,
            export_limit_kw=7.0,
            discharge_efficiency=0.95,
            proposal_solar_enabled=False,
            strategy="paced_export",
        ),
        forecast_energy_until_offpeak_kwh=None,
        current_snapshot=records[-1],
    )

    assert result.home_reserve_forecast_source == "recent_average"
    assert result.reserved_for_home_kwh is not None
    assert result.reserved_for_home_kwh > 1.3
    assert result.exportable_battery_energy_kwh == 0.0
    assert result.target_battery_export_power_kw == 0.0
    assert result.current_simulated_battery_export_power_kw == 0.0
    assert result.simulated_battery_export_kwh == 0.0
    assert result.battery_export_paused_for_home_reserve is True
    assert result.projected_grid_import_before_cheap_kwh is not None
    assert result.projected_grid_import_before_cheap_kwh > 0.0
    assert result.projected_soc_at_cheap_period_percent == 10.0


def test_current_load_is_final_home_reserve_fallback() -> None:
    """The live load protects the home when no learned or recent load exists."""
    now = datetime(2026, 8, 3, 21, 20, tzinfo=UTC)
    snapshot = Snapshot(
        timestamp=now,
        current_import_rate=28.3036,
        house_load_kw=1.5,
        grid_import_kw=1.5,
        next_offpeak_start=now + timedelta(hours=1),
    )
    config = SimulationConfig(
        battery_capacity_kwh=10.0,
        battery_reserve_percent=10.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        proposal_solar_enabled=False,
        strategy="paced_export",
    )

    plan = SimulationEngine()._current_plan(
        snapshot,
        [],
        battery_kwh=2.0,
        reserve_kwh=1.0,
        capacity=10.0,
        config=config,
        forecast_energy_until_offpeak_kwh=None,
    )

    assert plan["reserve_source"] == "current_load"
    assert plan["target_battery_export"] == 0.0
    assert plan["battery_export"] == 0.0
    assert plan["export_paused_for_home"] is True


def test_joined_power_down_session_reduces_pre_session_export() -> None:
    """Battery energy should be held for a joined session before the next charge."""
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    cheap_start = now + timedelta(hours=11.5)
    session_start = now + timedelta(hours=4)
    session_end = session_start + timedelta(hours=1)
    base = Snapshot(
        timestamp=now,
        current_import_rate=28.3,
        house_load_kw=1.0,
        grid_import_kw=1.0,
        next_offpeak_start=cheap_start,
    )
    joined = Snapshot(
        timestamp=now,
        current_import_rate=28.3,
        house_load_kw=1.0,
        grid_import_kw=1.0,
        next_offpeak_start=cheap_start,
        saving_session_joined=True,
        saving_session_start=session_start,
        saving_session_end=session_end,
        saving_session_octopoints_per_kwh=800,
    )
    config = SimulationConfig(
        battery_capacity_kwh=20.0,
        battery_reserve_percent=10.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        discharge_efficiency=0.95,
        proposal_solar_enabled=False,
        strategy="paced_export",
        saving_session_enabled=True,
    )
    engine = SimulationEngine()

    normal = engine._current_plan(
        base,
        [base],
        battery_kwh=20.0,
        reserve_kwh=2.0,
        capacity=20.0,
        config=config,
        forecast_energy_until_offpeak_kwh=4.0,
    )
    protected = engine._current_plan(
        joined,
        [joined],
        battery_kwh=20.0,
        reserve_kwh=2.0,
        capacity=20.0,
        config=config,
        forecast_energy_until_offpeak_kwh=4.0,
    )

    assert protected["saving_session_joined"] is True
    assert protected["battery_reserved_for_saving_session"] is True
    assert protected["battery_export_reduced_for_saving_session"] is True
    assert protected["saving_session_battery_reserve_kwh"] == 7.368
    assert protected["saving_session_export_target_kw"] == 6.0
    assert protected["target_battery_export"] < normal["target_battery_export"]
    assert protected["export_paused_for_home"] is False


def test_session_after_next_cheap_period_does_not_reduce_export_now() -> None:
    """A battery recharge before the event means no pre-session hold is needed yet."""
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    snapshot = Snapshot(
        timestamp=now,
        current_import_rate=28.3,
        house_load_kw=1.0,
        grid_import_kw=1.0,
        next_offpeak_start=now + timedelta(hours=2),
        saving_session_joined=True,
        saving_session_start=now + timedelta(hours=5),
        saving_session_end=now + timedelta(hours=6),
        saving_session_octopoints_per_kwh=800,
    )
    config = SimulationConfig(
        battery_capacity_kwh=20.0,
        battery_reserve_percent=10.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        discharge_efficiency=0.95,
        proposal_solar_enabled=False,
        strategy="paced_export",
    )

    plan = SimulationEngine()._current_plan(
        snapshot,
        [snapshot],
        battery_kwh=20.0,
        reserve_kwh=2.0,
        capacity=20.0,
        config=config,
        forecast_energy_until_offpeak_kwh=1.0,
    )

    assert plan["saving_session_joined"] is True
    assert plan["battery_reserved_for_saving_session"] is False
    assert plan["battery_export_reduced_for_saving_session"] is False
    assert plan["target_battery_export"] > 0.0


def test_active_power_down_maximises_kh7_export_and_adds_bonus() -> None:
    """An active joined session should cover home and use remaining KH7 output."""
    start = datetime(2026, 11, 1, 16, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    records = [
        Snapshot(
            timestamp=start,
            current_import_rate=28.3,
            house_load_kw=2.0,
            grid_import_kw=2.0,
            battery_soc=100.0,
            saving_session_joined=True,
            saving_session_start=start,
            saving_session_end=end,
            saving_session_octopoints_per_kwh=800,
            saving_session_import_baseline_period_kwh=0.5,
            saving_session_export_baseline_period_kwh=0.0,
            saving_session_import_baseline_total_kwh=1.0,
            saving_session_export_baseline_total_kwh=0.0,
            saving_session_baseline_period_start=start,
            saving_session_baseline_period_end=start + timedelta(minutes=30),
            saving_session_baseline_incomplete=True,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=30),
            current_import_rate=28.3,
            house_load_kw=2.0,
            grid_import_kw=2.0,
            saving_session_joined=True,
            saving_session_start=start,
            saving_session_end=end,
            saving_session_octopoints_per_kwh=800,
            saving_session_import_baseline_period_kwh=0.5,
            saving_session_export_baseline_period_kwh=0.0,
            saving_session_import_baseline_total_kwh=1.0,
            saving_session_export_baseline_total_kwh=0.0,
            saving_session_baseline_period_start=start + timedelta(minutes=30),
            saving_session_baseline_period_end=end,
            saving_session_baseline_incomplete=True,
        ),
        Snapshot(
            timestamp=end,
            current_import_rate=28.3,
            house_load_kw=2.0,
            grid_import_kw=2.0,
        ),
    ]

    result = SimulationEngine().simulate_today(
        records,
        end,
        SimulationConfig(
            battery_capacity_kwh=20.0,
            battery_initial_percent=100.0,
            battery_reserve_percent=10.0,
            max_discharge_kw=7.0,
            inverter_limit_kw=7.0,
            export_limit_kw=7.0,
            discharge_efficiency=0.95,
            export_rate_pence=12.0,
            proposal_solar_enabled=False,
            strategy="paced_export",
        ),
        current_snapshot=records[1],
    )

    assert result.saving_session_active is True
    assert result.current_simulated_battery_to_home_power_kw == 2.0
    assert result.current_simulated_battery_export_power_kw == 5.0
    assert result.current_simulated_battery_power_kw == 7.0
    assert result.current_simulated_grid_import_kw == 0.0
    assert result.current_simulated_grid_export_kw == 5.0
    assert result.saving_session_bonus_rate_pence == 100.0
    assert result.saving_session_baseline_net_kwh == 1.0
    assert result.saving_session_baseline_incomplete is True
    assert result.estimated_saving_session_rewardable_reduction_kwh == 6.0
    assert result.estimated_saving_session_bonus_pence == 600.0
    assert result.estimated_saving_session_export_income_pence == 60.0
    assert result.estimated_saving_session_total_income_pence == 660.0
    assert result.simulated_saving_session_bonus_pence == 600.0
    assert result.simulated_export_income_pence == 60.0
    assert result.simulated_cost_pence == -660.0


def test_active_power_down_battery_target_excludes_solar_export() -> None:
    """The battery-export target must not include solar already sent to grid."""
    now = datetime(2026, 6, 1, 16, 0, tzinfo=UTC)
    snapshot = Snapshot(
        timestamp=now,
        current_import_rate=28.3,
        house_load_kw=2.0,
        grid_import_kw=2.0,
        solar_power_kw=3.0,
        saving_session_joined=True,
        saving_session_start=now,
        saving_session_end=now + timedelta(hours=1),
        saving_session_octopoints_per_kwh=800,
    )
    config = SimulationConfig(
        battery_capacity_kwh=20.0,
        battery_reserve_percent=10.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        proposal_solar_enabled=False,
        strategy="paced_export",
    )

    plan = SimulationEngine()._current_plan(
        snapshot,
        [snapshot],
        battery_kwh=20.0,
        reserve_kwh=2.0,
        capacity=20.0,
        config=config,
        forecast_energy_until_offpeak_kwh=None,
    )

    assert plan["grid_export"] == 5.0
    assert plan["battery_export"] == 4.0
    assert plan["target_battery_export"] == 4.0


def test_power_down_bonus_is_unknown_without_baseline() -> None:
    """Normal 12p export remains visible when the Octopus baseline is unavailable."""
    now = datetime(2026, 11, 1, 16, 0, tzinfo=UTC)
    snapshot = Snapshot(
        timestamp=now,
        current_import_rate=28.3,
        house_load_kw=2.0,
        grid_import_kw=2.0,
        saving_session_joined=True,
        saving_session_start=now,
        saving_session_end=now + timedelta(hours=1),
        saving_session_octopoints_per_kwh=400,
    )
    config = SimulationConfig(
        battery_capacity_kwh=20.0,
        battery_reserve_percent=10.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        export_rate_pence=12.0,
        proposal_solar_enabled=False,
        strategy="paced_export",
    )

    plan = SimulationEngine()._saving_session_plan(snapshot, [snapshot], config)

    assert plan["saving_session_bonus_rate_pence"] == 50.0
    assert plan["estimated_saving_session_export_kwh"] == 5.0
    assert plan["estimated_saving_session_export_income_pence"] == 60.0
    assert plan["estimated_saving_session_rewardable_reduction_kwh"] is None
    assert plan["estimated_saving_session_bonus_pence"] is None
    assert plan["estimated_saving_session_total_income_pence"] is None


def test_cheap_period_site_import_includes_house_bypass_and_battery_charge() -> None:
    """A 2kW home plus 7kW battery charge is a valid 9kW site import."""
    now = datetime(2026, 8, 6, 0, 0, tzinfo=UTC)
    snapshot = Snapshot(
        timestamp=now,
        current_import_rate=3.4933,
        off_peak=True,
        house_load_kw=2.0,
        grid_import_kw=2.0,
    )
    config = SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_initial_percent=10.0,
        battery_reserve_percent=10.0,
        max_charge_kw=7.0,
        inverter_limit_kw=7.0,
        proposal_solar_enabled=False,
        site_import_limit_kw=None,
    )

    plan = SimulationEngine()._current_plan(
        snapshot,
        [snapshot],
        battery_kwh=5.642,
        reserve_kwh=5.642,
        capacity=56.42,
        config=config,
        forecast_energy_until_offpeak_kwh=None,
    )

    assert plan["battery_charge"] == 7.0
    assert plan["grid_bypass"] == 2.0
    assert plan["total_site_import"] == 9.0
    assert plan["grid_import"] == 9.0
    assert plan["total_kh7_output"] == 0.0


def test_site_import_limit_caps_cheap_battery_charge_not_house_bypass() -> None:
    """The configurable site limit should reduce only the flexible charge load."""
    now = datetime(2026, 8, 6, 0, 0, tzinfo=UTC)
    snapshot = Snapshot(
        timestamp=now,
        current_import_rate=3.4933,
        off_peak=True,
        house_load_kw=2.0,
        grid_import_kw=2.0,
    )
    config = SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_initial_percent=10.0,
        battery_reserve_percent=10.0,
        max_charge_kw=7.0,
        inverter_limit_kw=7.0,
        proposal_solar_enabled=False,
        site_import_limit_kw=8.0,
    )

    plan = SimulationEngine()._current_plan(
        snapshot,
        [snapshot],
        battery_kwh=5.642,
        reserve_kwh=5.642,
        capacity=56.42,
        config=config,
        forecast_energy_until_offpeak_kwh=None,
    )

    assert plan["battery_charge"] == 6.0
    assert plan["grid_bypass"] == 2.0
    assert plan["total_site_import"] == 8.0
    assert plan["site_import_headroom"] == 0.0
    assert plan["site_import_exceeded"] is False


def test_power_down_high_solar_exposes_shared_kh7_output() -> None:
    """Power Down solar and battery output should reconcile to the 7kW cap."""
    now = datetime(2026, 6, 1, 16, 0, tzinfo=UTC)
    snapshot = Snapshot(
        timestamp=now,
        current_import_rate=28.3,
        house_load_kw=2.0,
        grid_import_kw=2.0,
        solar_power_kw=3.0,
        saving_session_joined=True,
        saving_session_active=True,
        saving_session_start=now,
        saving_session_end=now + timedelta(hours=1),
    )
    config = SimulationConfig(
        battery_capacity_kwh=20.0,
        battery_reserve_percent=10.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        proposal_solar_enabled=False,
    )

    plan = SimulationEngine()._current_plan(
        snapshot,
        [snapshot],
        battery_kwh=20.0,
        reserve_kwh=2.0,
        capacity=20.0,
        config=config,
        forecast_energy_until_offpeak_kwh=None,
    )

    assert plan["battery_to_home"] == 0.0 or plan["battery_to_home"] == 0
    assert plan["battery_export"] == 4.0
    assert plan["grid_export"] == 5.0
    assert plan["total_kh7_output"] == 7.0


def test_simulation_exposes_eps_limit_separately_from_grid_output_limit() -> None:
    """The dashboard should not infer EPS capacity from the site-import path."""
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    snapshot = Snapshot(
        timestamp=now,
        current_import_rate=28.3,
        house_load_kw=1.0,
        grid_import_kw=1.0,
    )

    result = SimulationEngine().simulate_today(
        [snapshot],
        now,
        SimulationConfig(
            inverter_limit_kw=7.0,
            eps_output_limit_kw=6.5,
            site_import_limit_kw=12.0,
        ),
    )

    assert result.inverter_limit_kw == 7.0
    assert result.eps_output_limit_kw == 6.5
    assert result.site_import_limit_kw == 12.0


def test_awaiting_export_tariff_uses_solar_then_battery_and_never_exports() -> None:
    """No-export mode must self-consume PV and disable deliberate export."""
    start = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    cheap_start = start + timedelta(hours=11, minutes=30)
    records = [
        Snapshot(
            timestamp=start + timedelta(minutes=15 * index),
            current_import_rate=28.3,
            current_export_rate=12.0,
            house_load_kw=1.0,
            grid_import_kw=1.0,
            solar_power_kw=4.0,
            off_peak=False,
            next_offpeak_start=cheap_start,
        )
        for index in range(4)
    ]
    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(minutes=46),
        SimulationConfig(
            battery_capacity_kwh=20.0,
            battery_initial_percent=40.0,
            battery_reserve_percent=10.0,
            proposal_solar_enabled=False,
            export_rate_pence=12.0,
            export_tariff_status="awaiting",
            battery_export_enabled=True,
            strategy="paced_export",
        ),
        forecast_energy_until_offpeak_kwh=5.0,
        current_snapshot=records[-1],
    )

    assert result.no_export_mode_active is True
    assert result.export_tariff_active is False
    assert result.export_tariff_status == "awaiting"
    assert result.effective_export_rate_pence == 0.0
    assert result.strategy == "self_use"
    assert result.battery_export_enabled is False
    assert result.simulated_grid_export_kwh == 0.0
    assert result.simulated_battery_export_kwh == 0.0
    assert result.current_simulated_grid_export_kw == 0.0
    assert result.current_simulated_battery_export_power_kw == 0.0
    assert result.current_simulated_solar_to_battery_power_kw is not None
    assert result.current_simulated_solar_to_battery_power_kw > 0.0


def test_awaiting_export_tariff_cheap_period_uses_solar_aware_charge_target() -> None:
    """Cheap charging should stop at a forecast target rather than always 100%."""
    start = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    next_cheap = start + timedelta(hours=23, minutes=30)
    records = [
        Snapshot(
            timestamp=start + timedelta(minutes=30 * index),
            current_import_rate=3.49,
            house_load_kw=0.5,
            grid_import_kw=0.5,
            off_peak=True,
            next_offpeak_start=next_cheap,
        )
        for index in range(5)
    ]
    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(hours=2, minutes=1),
        SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_initial_percent=10.0,
            battery_reserve_percent=10.0,
            max_charge_kw=7.0,
            max_discharge_kw=7.0,
            proposal_solar_enabled=True,
            export_tariff_status="awaiting",
            export_rate_pence=12.0,
        ),
        forecast_energy_until_offpeak_kwh=18.0,
        current_snapshot=records[-1],
    )

    assert result.overnight_charge_target_percent is not None
    assert 10.0 < result.overnight_charge_target_percent < 100.0
    assert result.overnight_charge_target_kwh is not None
    assert result.forecast_home_until_next_cheap_kwh == 18.0
    assert result.forecast_solar_until_next_cheap_kwh is not None
    assert result.forecast_solar_credit_kwh is not None
    assert result.current_simulated_grid_export_kw == 0.0
    assert result.current_simulated_battery_export_power_kw == 0.0


def test_awaiting_export_tariff_target_excludes_remaining_cheap_home_load() -> None:
    """Overnight target should cover demand after cheap power, not during it."""
    start = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    cheap_end = start + timedelta(hours=5, minutes=30)
    next_cheap = start + timedelta(hours=23, minutes=30)
    records = [
        Snapshot(
            timestamp=start + timedelta(minutes=30 * index),
            current_import_rate=3.49,
            house_load_kw=1.0,
            grid_import_kw=1.0,
            off_peak=True,
            offpeak_end=cheap_end,
            next_offpeak_start=next_cheap,
        )
        for index in range(3)
    ]
    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(hours=1, minutes=1),
        SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_initial_percent=10.0,
            battery_reserve_percent=10.0,
            max_charge_kw=7.0,
            proposal_solar_enabled=False,
            export_tariff_status="awaiting",
        ),
        forecast_energy_until_offpeak_kwh=23.5,
        current_snapshot=records[-1],
    )

    # At the 01:00 current snapshot, 4.5 cheap hours remain. Their 4.5 kWh
    # should be removed from the learned 23.5 kWh forecast before setting the
    # battery target, because that demand will be served by cheap grid power.
    assert result.forecast_home_until_next_cheap_kwh == 19.0
    assert result.overnight_charge_target_kwh is not None
    assert result.overnight_charge_target_kwh < 30.0


def test_export_tariff_active_preserves_alpha4_paced_export_behaviour() -> None:
    """The new status switch must not alter alpha4 behaviour when active."""
    start = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    cheap_start = start + timedelta(hours=10)
    records = [
        Snapshot(
            timestamp=start + timedelta(minutes=30 * index),
            current_import_rate=28.3,
            house_load_kw=0.0,
            grid_import_kw=0.0,
            off_peak=False,
            next_offpeak_start=cheap_start,
        )
        for index in range(3)
    ]
    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(hours=1),
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=100.0,
            battery_reserve_percent=10.0,
            proposal_solar_enabled=False,
            export_tariff_status="active",
            export_rate_pence=12.0,
            battery_export_enabled=True,
            strategy="paced_export",
        ),
        forecast_energy_until_offpeak_kwh=2.0,
        current_snapshot=records[-1],
    )
    assert result.export_tariff_active is True
    assert result.effective_export_rate_pence == 12.0
    assert result.strategy == "paced_export"
    assert result.battery_export_enabled is True
    assert result.target_battery_export_power_kw is not None
    assert result.target_battery_export_power_kw > 0.0


def test_awaiting_export_tariff_power_down_does_not_reenable_export() -> None:
    """No-export status must override Power Down export optimisation."""
    start = datetime(2026, 8, 12, 18, 0, tzinfo=UTC)
    end = start + timedelta(hours=2)
    next_cheap = start + timedelta(hours=5, minutes=30)
    records = [
        Snapshot(
            timestamp=start + timedelta(minutes=15 * index),
            current_import_rate=28.3,
            house_load_kw=1.5,
            grid_import_kw=1.5,
            solar_power_kw=0.5,
            off_peak=False,
            next_offpeak_start=next_cheap,
            saving_session_joined=True,
            saving_session_active=True,
            saving_session_start=start,
            saving_session_end=end,
            saving_session_octopoints_per_kwh=16.0,
            saving_session_import_baseline_total_kwh=3.0,
        )
        for index in range(4)
    ]
    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(minutes=46),
        SimulationConfig(
            battery_capacity_kwh=20.0,
            battery_initial_percent=80.0,
            battery_reserve_percent=10.0,
            proposal_solar_enabled=False,
            export_tariff_status="awaiting",
            battery_export_enabled=True,
            saving_session_enabled=True,
        ),
        forecast_energy_until_offpeak_kwh=4.0,
        current_snapshot=records[-1],
    )

    assert result.saving_session_active is True
    assert result.saving_session_export_target_kw == 0.0
    assert result.current_simulated_grid_export_kw == 0.0
    assert result.current_simulated_battery_export_power_kw == 0.0
    assert result.battery_reserved_for_saving_session is False


def test_simulation_exposes_tariff_and_solar_flow_breakdown() -> None:
    """Scenario comparison needs auditable cheap/day and PV routing totals."""
    start = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    records = [
        Snapshot(
            timestamp=start,
            current_import_rate=3.5,
            off_peak=True,
            house_load_kw=1.0,
            grid_import_kw=1.0,
            solar_power_kw=0.0,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=30),
            current_import_rate=28.0,
            off_peak=False,
            house_load_kw=1.0,
            grid_import_kw=1.0,
            solar_power_kw=2.0,
        ),
        Snapshot(
            timestamp=start + timedelta(hours=1),
            current_import_rate=28.0,
            off_peak=False,
            house_load_kw=1.0,
            grid_import_kw=1.0,
            solar_power_kw=2.0,
        ),
    ]

    result = SimulationEngine().simulate_today(
        records,
        start + timedelta(hours=1, minutes=1),
        SimulationConfig(
            battery_capacity_kwh=10.0,
            battery_initial_percent=10.0,
            battery_reserve_percent=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            export_rate_pence=12.0,
            proposal_solar_enabled=False,
            battery_export_enabled=False,
        ),
    )

    assert result.simulated_grid_import_kwh is not None
    assert result.simulated_cheap_import_kwh is not None
    assert result.simulated_day_import_kwh is not None
    assert (
        abs(
            result.simulated_grid_import_kwh
            - result.simulated_cheap_import_kwh
            - result.simulated_day_import_kwh
        )
        <= 0.002
    )
    assert result.simulated_import_cost_pence is not None
    assert result.simulated_cheap_import_cost_pence is not None
    assert result.simulated_day_import_cost_pence is not None
    assert (
        abs(
            result.simulated_import_cost_pence
            - result.simulated_cheap_import_cost_pence
            - result.simulated_day_import_cost_pence
        )
        <= 0.02
    )
    assert result.simulated_solar_generation_kwh is not None
    assert result.simulated_solar_export_kwh is not None
