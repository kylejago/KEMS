"""ROI financial entity registration regression tests."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
ROI_SCOPE = ROOT / "custom_components" / "kems" / "roi_financial_scope.py"
ROI_DASHBOARD = ROOT / "custom_components" / "kems" / "kems_roi_lifetime_dashboard.yaml"


def test_financial_roi_entities_have_valid_registration_metadata() -> None:
    """All ROI financial entities must carry Home Assistant-valid metadata."""
    source = ROI_SCOPE.read_text(encoding="utf-8")
    dashboard = ROI_DASHBOARD.read_text(encoding="utf-8")

    expected = (
        "financial_commissioning_date",
        "financial_house_consumption",
        "financial_grid_import",
        "financial_grid_export",
        "financial_solar_generation",
        "financial_export_income",
    )
    for key in expected:
        assert f'key="{key}"' in source

    for dashboard_entity in (
        "sensor.kems_financial_commissioning_date",
        "sensor.kems_house_electricity_since_commissioning",
        "sensor.kems_financial_grid_import",
        "sensor.kems_financial_grid_export",
        "sensor.kems_financial_solar_generation",
        "sensor.kems_financial_export_income",
    ):
        assert dashboard_entity in dashboard

    for key in (
        "financial_house_consumption",
        "financial_grid_import",
        "financial_grid_export",
        "financial_solar_generation",
    ):
        assert re.search(
            rf'key="{key}".*?device_class=SensorDeviceClass\.ENERGY.*?'
            r"state_class=SensorStateClass\.TOTAL",
            source,
            re.DOTALL,
        )

    assert re.search(
        r'key="financial_export_income".*?'
        r"device_class=SensorDeviceClass\.MONETARY.*?"
        r"state_class=SensorStateClass\.TOTAL",
        source,
        re.DOTALL,
    )
