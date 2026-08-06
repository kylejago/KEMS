"""Regression tests for pre-installation lifetime accounting."""

from kems_core import should_accumulate_lifetime_value


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
