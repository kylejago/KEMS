"""Tests for KEMS domain models."""

from datetime import UTC, date, datetime

from kems_core import PeriodTotals, PowerDownResult, Snapshot


def test_snapshot_round_trip() -> None:
    """Snapshots should survive JSON-compatible persistence."""
    snapshot = Snapshot(
        timestamp=datetime(2026, 7, 30, 21, 0, tzinfo=UTC),
        current_import_rate=28.3,
        house_load_kw=1.25,
        off_peak=False,
    )

    restored = Snapshot.from_dict(snapshot.to_dict())

    assert restored == snapshot


def test_extra_intelligent_slot_requires_ohme_charging_confirmation() -> None:
    """Extra cheap slots are confirmed by Octopus and active Ohme charging."""
    assert Snapshot(off_peak=True).cheap_period_confirmed is True
    assert (
        Snapshot(
            off_peak=False,
            intelligent_slot=True,
            ev_charging=True,
        ).cheap_period_confirmed
        is True
    )
    assert (
        Snapshot(
            off_peak=False,
            intelligent_slot=True,
            ev_charging=False,
        ).cheap_period_confirmed
        is False
    )


def test_stale_intelligent_slot_cannot_confirm_a_cheap_period() -> None:
    """A stale extra-slot signal must fail closed even while the EV charges."""
    snapshot = Snapshot(
        off_peak=False,
        intelligent_slot=True,
        ev_charging=True,
        tariff_source_age_seconds={"intelligent_slot": 301.0},
        tariff_stale_fields=("intelligent_slot",),
    )

    assert snapshot.intelligent_slot_source_fresh is False
    assert snapshot.cheap_period_confirmed is False


def test_manual_offpeak_fallback_remains_usable_when_live_source_was_stale() -> None:
    """A safe resolved schedule may still confirm the standard cheap window."""
    snapshot = Snapshot(
        off_peak=True,
        tariff_source_age_seconds={"off_peak": 301.0},
        tariff_stale_fields=("off_peak",),
    )

    assert snapshot.cheap_period_confirmed is True


def test_snapshot_round_trip_preserves_tariff_freshness_metadata() -> None:
    """Tariff safety metadata must survive persisted-history round trips."""
    snapshot = Snapshot(
        timestamp=datetime(2026, 8, 13, 12, 0, tzinfo=UTC),
        tariff_source_age_seconds={"intelligent_slot": 301.0},
        tariff_stale_fields=("intelligent_slot",),
        tariff_source_data_age_seconds=301.0,
    )

    restored = Snapshot.from_dict(snapshot.to_dict())

    assert restored.tariff_source_age_seconds == {"intelligent_slot": 301.0}
    assert restored.tariff_stale_fields == ("intelligent_slot",)
    assert restored.tariff_source_data_age_seconds == 301.0


def test_period_totals_keep_actual_and_simulated_values_separate() -> None:
    """Native reporting summaries must not mix physical and modelled costs."""
    totals = PeriodTotals(
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 6),
        days_included=6,
        import_cost_pence=300.0,
        export_income_pence=25.0,
        gas_cost_pence=40.0,
        simulated_import_cost_pence=120.0,
        simulated_export_income_pence=220.0,
        simulated_net_cost_pence=-100.0,
    )

    payload = totals.to_dict()

    assert totals.actual_net_cost_pence == 315.0
    assert payload["actual_net_cost_pence"] == 315.0
    assert payload["simulated_net_cost_pence"] == -100.0
    assert payload["start_date"] == "2026-08-01"


def test_period_aggregation_marks_missing_historical_days() -> None:
    """Empty archived days remain visible rather than becoming silent zeros."""
    from kems_core import summarise_period_records

    totals = summarise_period_records(
        {
            "2026-08-04": {"grid_import_kwh": 5.0, "import_cost_pence": 90.0},
            "2026-08-05": {},
            "2026-08-06": {"grid_import_kwh": 2.0, "import_cost_pence": 40.0},
        },
        date(2026, 8, 4),
        date(2026, 8, 6),
        current_day=date(2026, 8, 6),
    )

    assert totals.grid_import_kwh == 7.0
    assert totals.complete_days == 1
    assert totals.incomplete_days == 1
    assert totals.data_complete is False


def test_period_aggregation_marks_stale_current_day_incomplete() -> None:
    """A current day with excluded stale intervals must not claim completeness."""
    from kems_core import PERIOD_DATA_COMPLETE_KEY, summarise_period_records

    totals = summarise_period_records(
        {
            "2026-08-07": {
                "grid_import_kwh": 4.0,
                PERIOD_DATA_COMPLETE_KEY: 0.0,
            }
        },
        date(2026, 8, 7),
        date(2026, 8, 7),
        current_day=date(2026, 8, 7),
    )

    assert totals.grid_import_kwh == 4.0
    assert totals.complete_days == 0
    assert totals.incomplete_days == 0
    assert totals.data_complete is False


def test_power_down_result_round_trip_preserves_completed_session() -> None:
    """The retained event result must survive Home Assistant restarts."""
    result = PowerDownResult(
        available=True,
        session_id="pd-2026-08-06",
        session_start=datetime(2026, 8, 6, 17, 0, tzinfo=UTC),
        session_end=datetime(2026, 8, 6, 18, 0, tzinfo=UTC),
        starting_simulated_soc_percent=65.0,
        finishing_simulated_soc_percent=54.0,
        planned_export_kwh=5.5,
        maximum_inverter_output_kw=7.0,
        ev_successfully_blocked=True,
        active_samples_observed=17,
        plan_safe_throughout=True,
        island_override_observed=False,
        completed_successfully=True,
        completion_reason="completed",
    )

    assert PowerDownResult.from_dict(result.to_dict()) == result
