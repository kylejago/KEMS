"""Alpha9.36 ROI financial entity registration regression tests."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.kems import sensor as sensor_module
from custom_components.kems.roi_financial_scope import install_financial_roi_scope


def test_financial_roi_entities_have_valid_registration_metadata() -> None:
    """All ROI financial entities must survive Home Assistant sensor validation."""
    install_financial_roi_scope()
    descriptions = {
        description.key: description for description in sensor_module.SENSORS
    }

    expected = {
        "financial_commissioning_date",
        "financial_house_consumption",
        "financial_grid_import",
        "financial_grid_export",
        "financial_solar_generation",
        "financial_export_income",
    }
    assert expected <= descriptions.keys()

    assert (
        descriptions["financial_commissioning_date"].device_class
        == SensorDeviceClass.DATE
    )

    for key in (
        "financial_house_consumption",
        "financial_grid_import",
        "financial_grid_export",
        "financial_solar_generation",
    ):
        description = descriptions[key]
        assert description.device_class == SensorDeviceClass.ENERGY
        assert description.state_class == SensorStateClass.TOTAL
        assert description.native_unit_of_measurement == "kWh"

    export_income = descriptions["financial_export_income"]
    assert export_income.device_class == SensorDeviceClass.MONETARY
    assert export_income.state_class == SensorStateClass.TOTAL
    assert export_income.native_unit_of_measurement == "GBP"
