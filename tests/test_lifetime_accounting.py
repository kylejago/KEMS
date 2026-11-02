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


def test_alpha9170_all_time_happy_hour_uses_verified_daily_rows_only() -> None:
    """All-time must agree with month/year; keep supplier gross bill untouched."""
    import ast
    from datetime import UTC, date, datetime
    from pathlib import Path
    from types import SimpleNamespace

    from kems_core import (
        LifetimeLedger,
        PeriodTotals,
        period_value_keys,
        period_value_kwargs,
    )

    path = Path(__file__).parents[1] / "custom_components" / "kems" / "lifetime.py"
    module = ast.parse(path.read_text())
    owner = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "LifetimeLedgerRecorder"
    )
    method = next(
        node
        for node in owner.body
        if isinstance(node, ast.FunctionDef) and node.name == "_all_time_summary"
    )
    standalone = ast.ClassDef(
        name="Recorder", bases=[], keywords=[], body=[method], decorator_list=[]
    )
    namespace = {
        "date": date,
        "PeriodTotals": PeriodTotals,
        "period_value_keys": period_value_keys,
        "period_value_kwargs": period_value_kwargs,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[standalone], type_ignores=[])),
            "<all-time-summary>",
            "exec",
        ),
        namespace,
    )
    recorder = namespace["Recorder"]()
    ledger = LifetimeLedger()
    ledger.first_observation = datetime(2026, 10, 1, tzinfo=UTC)
    ledger.import_cost_pence = 1500.0
    recorder._ledger = ledger
    recorder._tracking_date = date(2026, 11, 2)
    recorder._tracking_values = {"import_cost_pence": 100.0}
    recorder._daily_records = {
        "2026-11-01": {
            "import_cost_pence": 1400.0,
            "happy_hour_estimated_credit_pence": 261.729,
            "happy_hour_credited_import_kwh": 7.294,
        }
    }
    summary = recorder._all_time_summary(date(2026, 11, 2))
    assert summary.happy_hour_estimated_credit_pence == 261.729
    assert summary.happy_hour_credited_import_kwh == 7.294
    assert summary.import_cost_pence == 1500.0
    assert summary.actual_net_after_estimated_happy_hour_credit_pence == (
        summary.actual_net_cost_pence - 261.729
    )


def test_alpha9170_all_time_happy_hour_includes_active_day_once() -> None:
    """Do not double-count today's high-water credit when rollover occurs."""
    import ast
    from datetime import date
    from pathlib import Path

    from kems_core import (
        LifetimeLedger,
        PeriodTotals,
        period_value_keys,
        period_value_kwargs,
    )

    module = ast.parse(
        (Path(__file__).parents[1] / "custom_components/kems/lifetime.py").read_text()
    )
    method = next(
        node
        for cls in module.body
        if isinstance(cls, ast.ClassDef) and cls.name == "LifetimeLedgerRecorder"
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "_all_time_summary"
    )
    compiled = ast.ClassDef(
        name="Recorder", bases=[], keywords=[], body=[method], decorator_list=[]
    )
    ns = dict(
        PeriodTotals=PeriodTotals,
        period_value_keys=period_value_keys,
        period_value_kwargs=period_value_kwargs,
    )
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[compiled], type_ignores=[])),
            "<all-time-day>",
            "exec",
        ),
        ns,
    )
    obj = ns["Recorder"]()
    obj._ledger = LifetimeLedger()
    obj._daily_records = {
        "2026-11-01": {
            "happy_hour_estimated_credit_pence": 261.729,
            "happy_hour_credited_import_kwh": 7.294,
        }
    }
    obj._tracking_date = date(2026, 11, 2)
    obj._tracking_values = {
        "happy_hour_estimated_credit_pence": 120.0,
        "happy_hour_credited_import_kwh": 4.0,
    }
    summary = obj._all_time_summary(date(2026, 11, 2))
    assert summary.happy_hour_estimated_credit_pence == 381.729
    assert summary.happy_hour_credited_import_kwh == 11.294
