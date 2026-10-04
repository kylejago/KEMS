"""Alpha9.36 ROI financial entity registration regression tests."""

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

    expected = {
        "financial_commissioning_date": "sensor.kems_financial_commissioning_date",
        "financial_house_consumption": (
            "sensor.kems_house_electricity_since_commissioning"
        ),
        "financial_grid_import": "sensor.kems_grid_import_since_commissioning",
        "financial_grid_export": "sensor.kems_grid_export_since_commissioning",
        "financial_solar_generation": (
            "sensor.kems_solar_generation_since_commissioning"
        ),
        "financial_export_income": (
            "sensor.kems_paid_export_income_since_commissioning"
        ),
    }
    for key, entity_id in expected.items():
        assert f'key="{key}"' in source
        assert entity_id in dashboard

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
