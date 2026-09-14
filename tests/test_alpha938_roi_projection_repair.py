"""Alpha9.38 live-ROI projection and dashboard repair tests."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from custom_components.kems.kems_core import (
    LifetimeLedger,
    PeriodTotals,
    ROIConfig,
    ROIEngine,
    SimulationState,
)
from custom_components.kems.roi_financial_scope import roi_scoped_ledger

ROOT = Path(__file__).parents[1]
ROI_DASHBOARD = ROOT / "custom_components" / "kems" / "kems_roi_lifetime_dashboard.yaml"


def test_alpha938_retained_learning_projects_actual_is_commissioned() -> None:
    """Forty-five days of learning can project while only three live days pay back."""
    ledger = LifetimeLedger(
        first_observation=datetime(2026, 8, 1, 23, 10),
        observed_days=45,
        system_operating_days=45,
        simulated_system_value_pence=19000.0,
        simulated_export_income_pence=3500.0,
        simulated_solar_generation_kwh=620.0,
        simulated_grid_export_kwh=280.0,
        actual_avoided_import_value_pence=9999.0,
        actual_system_value_pence=9999.0,
    )
    period = PeriodTotals(
        start_date=date(2026, 9, 12),
        end_date=date(2026, 9, 14),
        days_included=3,
        actual_avoided_import_value_pence=635.0,
        actual_system_value_pence=635.0,
    )
    now = datetime(2026, 9, 14, 22, 0)
    scoped = roi_scoped_ledger(
        ledger,
        period,
        commissioning_date=date(2026, 9, 12),
        now=now,
    )
    state = ROIEngine().evaluate(
        scoped,
        SimulationState(
            ready=True,
            actual_system_value_pence=268.0,
            effective_export_rate_pence=15.0,
            export_tariff_active=True,
        ),
        now,
        ROIConfig(commissioning_date=date(2026, 9, 12)),
    )

    assert state.ready is True
    assert state.predicted_annual_saving_gbp is not None
    assert state.predicted_annual_saving_gbp > 0
    assert state.predicted_payback_years is not None
    assert state.predicted_net_value_gbp is not None
    assert state.actual_value_created_total_gbp == 6.35
    assert state.actual_value_created_today_gbp == 2.68
    assert state.observed_days == 45
    assert state.operating_days == 3


def test_alpha938_dashboard_references_live_registered_house_entity() -> None:
    content = ROI_DASHBOARD.read_text(encoding="utf-8")
    assert "sensor.kems_house_electricity_since_commissioning" in content
    assert "sensor.kems_house_consumption_since_commissioning" not in content
    assert "Full KEMS projection — retained evidence" in content
    assert "including battery and paid export" in content


def test_alpha938_release_identity_and_roi_only_scope() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.38"
    assert reason.startswith("Alpha9.38 repairs Live ROI")
    assert (
        "complete configured future system including battery and paid export" in reason
    )
    assert "simulated battery/export gains never enter actual payback" in reason
    assert "no optimiser allocation" in reason
    assert "FoxESS command/write authority changes" in reason
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.3"
    assert bundle["components"]["property_web"]["version"] == "0.9.0-alpha9-web.0"
    assert bundle["components"]["public_web"]["version"] == "0.9.0-alpha9-public.0"
