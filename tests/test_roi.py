"""Tests for KEMS ROI and lifetime financial calculations."""

from datetime import UTC, date, datetime, timedelta

from kems_core import LifetimeLedger, ROIConfig, ROIEngine, SimulationState


def test_pre_install_roi_annualises_simulated_value() -> None:
    """Retained simulated value should produce a transparent ROI forecast."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    ledger = LifetimeLedger(
        first_observation=now - timedelta(days=29),
        last_updated=now,
        observed_days=30,
        simulated_system_value_pence=10000.0,
    )

    result = ROIEngine().evaluate(
        ledger,
        SimulationState(simulated_system_value_pence=400.0),
        now,
        ROIConfig(system_cost_gbp=1000.0, forecast_years=20),
    )

    assert result.ready is True
    assert result.status == "Pre-install ROI simulation"
    assert result.system_installed is False
    assert result.predicted_annual_saving_gbp == 1216.67
    assert result.predicted_payback_years is not None
    assert result.predicted_payback_date is not None
    assert result.predicted_net_value_gbp is not None


def test_paid_back_system_switches_to_profit_mode() -> None:
    """Actual ROI should expose profit after the investment is recovered."""
    now = datetime(2034, 9, 20, 12, 0, tzinfo=UTC)
    ledger = LifetimeLedger(
        first_observation=now - timedelta(days=400),
        last_updated=now,
        commissioning_date=date(2026, 8, 1),
        paid_back_date=date(2034, 9, 18),
        observed_days=401,
        system_operating_days=2973,
        actual_system_value_pence=250000.0,
        simulated_system_value_pence=260000.0,
        system_operating_cost_pence=10000.0,
    )

    result = ROIEngine().evaluate(
        ledger,
        SimulationState(actual_system_value_pence=500.0),
        now,
        ROIConfig(
            system_cost_gbp=1000.0,
            commissioning_date=date(2026, 8, 1),
            manual_system_costs_gbp=100.0,
        ),
    )

    assert result.system_installed is True
    assert result.system_paid_back is True
    assert result.status == "System paid back — profit mode"
    assert result.actual_value_created_total_gbp == 2500.0
    assert result.operating_costs_gbp == 200.0
    assert result.actual_net_profit_gbp == 1300.0
    assert result.actual_payback_remaining_gbp == 0.0
    assert result.actual_payback_date is not None


def test_lifetime_ledger_round_trip() -> None:
    """Permanent totals should survive JSON-compatible storage."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    ledger = LifetimeLedger(
        first_observation=now,
        last_updated=now,
        commissioning_date=date(2026, 8, 1),
        paid_back_date=date(2034, 9, 18),
        grid_import_kwh=123.4,
        export_income_pence=567.8,
    )

    restored = LifetimeLedger.from_dict(ledger.to_dict())

    assert restored.first_observation == now
    assert restored.commissioning_date == date(2026, 8, 1)
    assert restored.paid_back_date == date(2034, 9, 18)
    assert restored.grid_import_kwh == 123.4
    assert restored.export_income_pence == 567.8
