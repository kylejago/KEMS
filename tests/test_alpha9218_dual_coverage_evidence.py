"""Alpha9.218: report existing ledger totals without asserting meter completeness."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from kems_core.period_coverage_probe import observation_coverage_probe
from kems_core.whatsapp_message_plans import completed_period_message
from kems_core.periods import (
    period_value_keys,
    recorded_totals_present,
    summarise_period_records,
)


def test_incomplete_simulation_still_has_reported_ledger_totals() -> None:
    rows = {
        "2026-11-15": {
            "__data_complete": 0.0,
            "__data_coverage_percent": 93.75,
            "grid_import_kwh": 84.5,
            "grid_export_kwh": 31.0,
            "import_cost_pence": 1004.02,
            "export_income_pence": 780.41,
        }
    }
    untouched = {key: dict(value) for key, value in rows.items()}
    result = summarise_period_records(
        rows,
        date(2026, 11, 15),
        date(2026, 11, 15),
        current_day=date(2026, 11, 16),
    )
    assert result.data_complete is False
    assert result.complete_days == 0
    assert result.incomplete_days == 1
    assert result.simulation_coverage_complete is False
    assert result.recorded_totals_available is True
    assert result.recorded_days_with_totals == 1
    assert result.independent_meter_completeness == "not_verified"
    assert result.grid_import_kwh == 84.5
    assert result.grid_export_kwh == 31.0
    assert result.import_cost_pence == 1004.02
    assert result.to_dict()["simulation_incomplete_days"] == 1
    assert rows == untouched


def test_absent_ledger_and_zero_replay_are_not_mistaken_for_meter_readings() -> None:
    day = date(2026, 11, 15)
    assert not recorded_totals_present({})
    assert not recorded_totals_present(
        {"__data_complete": 0.0, "__data_coverage_percent": 0.0, "grid_import_kwh": 0.0}
    )
    for rows in ({}, {"2026-11-15": {}}):
        result = summarise_period_records(
            rows, day, day, current_day=date(2026, 11, 16)
        )
        assert not result.recorded_totals_available
    assert not any(
        key in period_value_keys()
        for key in (
            "recorded_totals_available",
            "recorded_days_with_totals",
            "simulation_coverage_complete",
            "independent_meter_completeness",
        )
    )


def _snap(
    t: datetime,
    *,
    load: float | None = 1.0,
    rate: float | None = 0.2,
    grid_import: float | None = 0.1,
    grid_export: float | None = 0.0,
    stale: tuple[str, ...] = (),
):
    return SimpleNamespace(
        timestamp=t,
        house_load_kw=load,
        grid_import_kw=grid_import,
        grid_export_kw=grid_export,
        current_import_rate=rate,
        stale_fields=stale,
        tariff_stale_fields=(),
    )


def test_grid_readings_are_counted_even_when_simulation_load_is_missing() -> None:
    start = datetime(2026, 11, 16, 12, tzinfo=UTC)
    samples = [
        _snap(start, load=None),
        _snap(start + timedelta(minutes=5), load=None),
        _snap(start + timedelta(minutes=10), rate=None),
    ]
    r = observation_coverage_probe(samples, start + timedelta(hours=1))
    day = r["day_rows"][0]
    assert day["pair_count"] == 2
    assert day["simulation_replay_eligible_pairs"] == 0
    assert day["independent_grid_import_observed_pairs"] == 2
    assert day["independent_grid_export_observed_pairs"] == 2
    assert day["independent_grid_both_observed_pairs"] == 2
    assert day["independent_grid_observed_pair_percent"] == 100
    assert day["independent_meter_completeness"] == "not_verified"
    assert r["independent_meter_observation_does_not_prove_full_day"]


def test_stale_and_nonfinite_physical_samples_are_not_counted() -> None:
    start = datetime(2026, 11, 16, 12, tzinfo=UTC)
    samples = [
        _snap(start, grid_import=float("nan")),
        _snap(start + timedelta(minutes=5), stale=("grid_export_kw",)),
    ]
    day = observation_coverage_probe(samples, start + timedelta(minutes=5))["day_rows"][
        0
    ]
    assert day["independent_grid_import_observed_pairs"] == 0
    assert day["independent_grid_export_observed_pairs"] == 0
    assert day["independent_grid_both_observed_pairs"] == 0


def test_daily_recap_shows_reported_totals_without_claiming_complete_metering() -> None:
    period = summarise_period_records(
        {
            "2026-11-15": {
                "__data_complete": 0.0,
                "__data_coverage_percent": 93.75,
                "grid_import_kwh": 84.5,
                "grid_export_kwh": 31.0,
                "solar_generation_kwh": 12.7,
                "import_cost_pence": 1004.02,
                "export_income_pence": 780.41,
                "gas_cost_pence": 120.0,
                "happy_hour_estimated_credit_pence": 474.048,
            }
        },
        date(2026, 11, 15),
        date(2026, 11, 15),
        current_day=date(2026, 11, 16),
    )
    _, message = completed_period_message(
        {"yesterday": period.to_dict()},
        datetime(2026, 11, 16, 8, tzinfo=UTC),
        weekly=False,
        standing_charge_pence_per_day=55.5236,
    )
    assert "Partial coverage" in message
    assert "Saved totals are shown" in message
    assert "Independent meter completeness not verified" in message
    assert "Grid import: 84.50 kWh" in message
    assert "Gross energy total (dashboard basis): £3.99" in message
    assert "Net after estimated Happy Hour refund: £-0.75" in message


def test_no_replay_coverage_does_not_publish_zero_placeholder_as_actual() -> None:
    period = summarise_period_records(
        {
            "2026-11-15": {
                "__data_complete": 0.0,
                "__data_coverage_percent": 0.0,
                "grid_import_kwh": 0.0,
                "grid_export_kwh": 0.0,
            }
        },
        date(2026, 11, 15),
        date(2026, 11, 15),
        current_day=date(2026, 11, 16),
    )
    assert period.days_included == 1
    assert period.recorded_totals_available is False
    _, message = completed_period_message(
        {"yesterday": period.to_dict()},
        datetime(2026, 11, 16, 8, tzinfo=UTC),
        weekly=False,
    )
    assert "No recorded period totals available" in message
    assert "Grid import: 0.00 kWh" not in message
