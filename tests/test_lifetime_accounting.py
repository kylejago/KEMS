"""Regression tests for pre-installation lifetime accounting."""

from kems_core import (
    reconciled_observed_lifetime_values,
    reconciled_simulated_lifetime_values,
    should_accumulate_lifetime_value,
)


def test_observed_baseline_accumulates_before_commissioning() -> None:
    for key in (
        "house_consumption_kwh",
        "grid_import_kwh",
        "import_cost_pence",
        "gas_consumption_kwh",
        "gas_cost_pence",
        "simulated_system_value_pence",
    ):
        assert should_accumulate_lifetime_value(key, installed=False) is True


def test_actual_system_value_waits_for_commissioning() -> None:
    assert (
        should_accumulate_lifetime_value(
            "actual_system_value_pence",
            installed=False,
        )
        is False
    )
    assert (
        should_accumulate_lifetime_value(
            "actual_system_value_pence",
            installed=True,
        )
        is True
    )


def test_simulated_avoided_import_value_accumulates_before_commissioning() -> None:
    assert (
        should_accumulate_lifetime_value(
            "simulated_avoided_import_value_pence",
            installed=False,
        )
        is True
    )


def test_simulated_lifetime_reconciles_to_daily_ledger() -> None:
    totals = reconciled_simulated_lifetime_values(
        [
            {
                "simulated_grid_export_kwh": 100.0,
                "simulated_battery_export_kwh": 40.0,
                "simulated_export_income_pence": 1200.0,
            },
            {
                "simulated_grid_export_kwh": 20.0,
                "simulated_battery_export_kwh": 10.0,
                "simulated_export_income_pence": 240.0,
            },
        ],
        {
            "simulated_grid_export_kwh": 2.674,
            "simulated_battery_export_kwh": 1.237,
            "simulated_export_income_pence": 32.088,
        },
    )

    assert totals["simulated_grid_export_kwh"] == 122.674
    assert totals["simulated_battery_export_kwh"] == 51.237
    assert totals["simulated_export_income_pence"] == 1472.088


def test_simulated_lifetime_reconciliation_allows_downward_revision() -> None:
    stale_high_water = 43.495
    totals = reconciled_simulated_lifetime_values(
        [],
        {
            "simulated_grid_export_kwh": 43.169,
            "simulated_battery_export_kwh": 15.0,
            "simulated_export_income_pence": 518.028,
        },
    )

    assert totals["simulated_grid_export_kwh"] == 43.169
    assert totals["simulated_grid_export_kwh"] < stale_high_water


def test_observed_lifetime_reconciles_to_daily_ledger_after_stale_source() -> None:
    stale_lifetime_high_water = 195.278
    totals = reconciled_observed_lifetime_values(
        [
            {
                "house_consumption_kwh": 150.0,
                "grid_import_kwh": 150.0,
                "import_cost_pence": 3000.0,
            }
        ],
        {
            "house_consumption_kwh": 41.27,
            "grid_import_kwh": 41.27,
            "import_cost_pence": 938.82,
        },
    )

    assert round(totals["house_consumption_kwh"], 3) == 191.27
    assert round(totals["grid_import_kwh"], 3) == 191.27
    assert round(totals["import_cost_pence"], 2) == 3938.82
    assert totals["house_consumption_kwh"] < stale_lifetime_high_water


def test_observed_reconciliation_does_not_rebuild_commissioned_value() -> None:
    totals = reconciled_observed_lifetime_values(
        [{"actual_system_value_pence": 123.0, "house_consumption_kwh": 1.0}],
    )

    assert "actual_system_value_pence" not in totals
    assert totals["house_consumption_kwh"] == 1.0
