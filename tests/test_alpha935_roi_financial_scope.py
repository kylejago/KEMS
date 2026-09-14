"""Alpha9.35 commissioning-scoped ROI regression tests."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import yaml

from custom_components.kems.kems_core import LifetimeLedger, PeriodTotals
from custom_components.kems.roi_financial_scope import (
    financial_period_from_records,
    roi_scoped_ledger,
)

ROOT = Path(__file__).parents[1]
ROI_SCOPE = ROOT / "custom_components" / "kems" / "roi_financial_scope.py"
ROI_DASHBOARD = (
    ROOT / "custom_components" / "kems" / "kems_roi_lifetime_dashboard.yaml"
)
ROI_ACCOUNTING = ROOT / "custom_components" / "kems" / "roi_accounting.py"


def test_financial_period_starts_at_commissioning() -> None:
    """Every ROI evidence total must begin on the chosen financial start date."""
    period = financial_period_from_records(
        {
            "2026-09-11": {
                "house_consumption_kwh": 1000.0,
                "grid_import_kwh": 900.0,
                "grid_export_kwh": 80.0,
                "solar_generation_kwh": 90.0,
                "export_income_pence": 5000.0,
                "simulated_system_value_pence": 9999.0,
            },
            "2026-09-12": {
                "house_consumption_kwh": 20.0,
                "grid_import_kwh": 12.0,
                "grid_export_kwh": 4.0,
                "solar_generation_kwh": 14.0,
                "export_income_pence": 0.0,
                "actual_system_value_pence": 250.0,
                "simulated_system_value_pence": 400.0,
            },
            "2026-09-13": {
                "house_consumption_kwh": 24.0,
                "grid_import_kwh": 9.0,
                "grid_export_kwh": 16.0,
                "solar_generation_kwh": 25.0,
                "export_income_pence": 0.0,
                "actual_system_value_pence": 340.0,
                "simulated_system_value_pence": 500.0,
            },
        },
        tracking_date=date(2026, 9, 14),
        tracking_values={
            "house_consumption_kwh": 22.0,
            "grid_import_kwh": 13.0,
            "grid_export_kwh": 5.0,
            "solar_generation_kwh": 14.0,
            "export_income_pence": 0.0,
            "actual_system_value_pence": 270.0,
            "simulated_system_value_pence": 600.0,
        },
        commissioning_date=date(2026, 9, 12),
        today=date(2026, 9, 14),
    )

    assert period.start_date == date(2026, 9, 12)
    assert period.end_date == date(2026, 9, 14)
    assert period.house_consumption_kwh == 66.0
    assert period.grid_import_kwh == 34.0
    assert period.grid_export_kwh == 25.0
    assert period.solar_generation_kwh == 53.0
    assert period.export_income_pence == 0.0
    assert period.actual_system_value_pence == 860.0
    assert period.simulated_system_value_pence == 1500.0


def test_financial_period_is_empty_without_selected_start() -> None:
    """ROI evidence must not silently fall back to all-time history."""
    period = financial_period_from_records(
        {"2026-09-14": {"grid_import_kwh": 42.0}},
        tracking_date=None,
        tracking_values=None,
        commissioning_date=None,
        today=date(2026, 9, 14),
    )
    assert period.start_date is None
    assert period.grid_import_kwh == 0.0
    assert period.house_consumption_kwh == 0.0


def test_projection_ledger_uses_commissioned_window() -> None:
    """Post-live projection must not annualise older pre-commission simulation."""
    original = LifetimeLedger(
        first_observation=datetime(2026, 8, 1, 0, 0),
        observed_days=45,
        simulated_system_value_pence=50000.0,
        simulated_export_income_pence=10000.0,
        simulated_solar_generation_kwh=900.0,
        simulated_grid_export_kwh=600.0,
        actual_system_value_pence=634.0,
    )
    period = PeriodTotals(
        start_date=date(2026, 9, 12),
        end_date=date(2026, 9, 14),
        days_included=3,
        simulated_system_value_pence=1500.0,
        simulated_export_income_pence=200.0,
        simulated_solar_generation_kwh=53.0,
        simulated_grid_export_kwh=25.0,
        actual_system_value_pence=634.0,
    )
    now = datetime(2026, 9, 14, 18, 0)

    scoped = roi_scoped_ledger(
        original,
        period,
        commissioning_date=date(2026, 9, 12),
        now=now,
    )

    assert scoped is not original
    assert scoped.first_observation == datetime(2026, 9, 12, 0, 0)
    assert scoped.observed_days == 3
    assert scoped.simulated_system_value_pence == 1500.0
    assert scoped.simulated_export_income_pence == 200.0
    assert scoped.simulated_solar_generation_kwh == 53.0
    assert scoped.simulated_grid_export_kwh == 25.0
    assert original.simulated_system_value_pence == 50000.0


def test_roi_dashboard_uses_financial_scope_for_evidence() -> None:
    """The ROI tab must not display all-time energy or export-income entities."""
    content = ROI_DASHBOARD.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    assert [view["path"] for view in parsed["views"]] == ["roi"]
    assert "sensor.kems_financial_commissioning_date" in content
    assert "sensor.kems_financial_solar_generation" in content
    assert "sensor.kems_financial_grid_import" in content
    assert "sensor.kems_financial_grid_export" in content
    assert "sensor.kems_financial_house_consumption" in content
    assert "sensor.kems_financial_export_income" in content
    assert "sensor.kems_lifetime_grid_import" not in content
    assert "sensor.kems_lifetime_grid_export" not in content
    assert "sensor.kems_lifetime_solar_generation" not in content
    assert "sensor.kems_lifetime_house_consumption" not in content
    assert "sensor.kems_lifetime_export_income" not in content
    assert "Current projection — since commissioning" in content


def test_financial_scope_extension_is_installed() -> None:
    """The runtime extension must be activated before coordinator setup runs."""
    accounting = ROI_ACCOUNTING.read_text(encoding="utf-8")
    scope = ROI_SCOPE.read_text(encoding="utf-8")
    assert "install_financial_roi_scope" in accounting
    assert 'summaries["financial"] = financial' in scope
    assert "ROIEngine.evaluate = evaluate" in scope
    assert 'key="financial_commissioning_date"' in scope
    assert 'key="financial_house_consumption"' in scope
    assert 'key="financial_grid_import"' in scope
    assert 'key="financial_grid_export"' in scope
    assert 'key="financial_solar_generation"' in scope
    assert 'key="financial_export_income"' in scope
