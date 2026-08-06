"""Regression tests for pre-installation lifetime accounting."""

from kems_core import (
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
