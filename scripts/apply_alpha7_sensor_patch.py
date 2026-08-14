"""One-shot generator for the Alpha 7 forecast-validation sensor patch."""

from pathlib import Path

SENSOR = Path("custom_components/kems/sensor.py")
MODELS = Path("custom_components/kems/kems_core/models.py")


def patch_sensor() -> None:
    """Add coordinator-backed forecast validation sensors once."""
    text = SENSOR.read_text(encoding="utf-8")
    marker = "class KEMSForecastValidationSensor(KEMSEntity, SensorEntity):"
    if marker in text:
        return

    old = """    entities.append(KEMSSourceValidationSensor(coordinator))
    async_add_entities(entities)
"""
    new = """    entities.append(KEMSSourceValidationSensor(coordinator))
    entities.extend(
        KEMSForecastValidationSensor(coordinator, description)
        for description in FORECAST_VALIDATION_SENSORS
    )
    async_add_entities(entities)
"""
    if old not in text:
        raise RuntimeError("sensor setup anchor not found")
    text = text.replace(old, new, 1)

    addition = r'''

ForecastValidationValueFn = Callable[[Any], Any]
ForecastValidationAttributesFn = Callable[[Any], Mapping[str, Any]]


@dataclass(frozen=True, kw_only=True)
class KEMSForecastValidationSensorDescription(SensorEntityDescription):
    """Describe one forecast-vs-actual validation sensor."""

    value_fn: ForecastValidationValueFn
    attributes_fn: ForecastValidationAttributesFn | None = None


def _forecast_validation_attributes(coordinator) -> Mapping[str, Any]:
    """Expose full validation metrics plus retained pre-day evidence."""
    return {
        **coordinator.forecast_validation_state.to_dict(),
        "pending_observation_count": len(
            coordinator.forecast_validation_observations
        ),
        "pending_observations": [
            item.to_dict()
            for item in coordinator.forecast_validation_observations[-7:]
        ],
    }


FORECAST_VALIDATION_SENSORS: tuple[
    KEMSForecastValidationSensorDescription, ...
] = (
    KEMSForecastValidationSensorDescription(
        key="forecast_validation_status",
        name="Forecast validation status",
        icon="mdi:chart-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.status,
        attributes_fn=_forecast_validation_attributes,
    ),
    KEMSForecastValidationSensorDescription(
        key="forecast_validation_days",
        name="Forecast validation days",
        icon="mdi:calendar-check-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.days_validated,
    ),
    KEMSForecastValidationSensorDescription(
        key="forecast_validation_solar_days",
        name="Forecast validation solar days",
        icon="mdi:solar-power",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.solar_days_validated,
    ),
    KEMSForecastValidationSensorDescription(
        key="forecast_validation_house_days",
        name="Forecast validation house days",
        icon="mdi:home-clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.house_days_validated,
    ),
    KEMSForecastValidationSensorDescription(
        key="forecast_validation_confidence",
        name="Forecast validation confidence",
        icon="mdi:progress-check",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.confidence_percent,
    ),
    KEMSForecastValidationSensorDescription(
        key="forecast_validation_best_solar_source",
        name="Forecast validation best solar source",
        icon="mdi:source-branch-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.best_solar_source,
    ),
    KEMSForecastValidationSensorDescription(
        key="forecast_validation_forecast_solar_mae",
        name="Forecast validation Forecast Solar MAE",
        icon="mdi:chart-bell-curve",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.forecast_solar_mae_kwh,
    ),
    KEMSForecastValidationSensorDescription(
        key="forecast_validation_open_meteo_mae",
        name="Forecast validation Open Meteo MAE",
        icon="mdi:weather-partly-cloudy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.open_meteo_mae_kwh,
    ),
    KEMSForecastValidationSensorDescription(
        key="forecast_validation_fused_solar_mae",
        name="Forecast validation fused solar MAE",
        icon="mdi:call-merge",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.fused_solar_mae_kwh,
    ),
    KEMSForecastValidationSensorDescription(
        key="forecast_validation_house_mae",
        name="Forecast validation house MAE",
        icon="mdi:home-analytics",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.house_mae_kwh,
    ),
    KEMSForecastValidationSensorDescription(
        key="forecast_validation_correction_factor",
        name="Forecast validation correction factor",
        icon="mdi:tune-variant",
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.suggested_fused_correction_factor,
    ),
)


class KEMSForecastValidationSensor(KEMSEntity, SensorEntity):
    """Expose retained forecast-vs-actual evidence in Home Assistant."""

    entity_description: KEMSForecastValidationSensorDescription

    def __init__(
        self,
        coordinator,
        description: KEMSForecastValidationSensorDescription,
    ) -> None:
        """Initialise a forecast validation sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the current validation metric."""
        return self.entity_description.value_fn(
            self.coordinator.forecast_validation_state
        )

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return full evidence on the headline validation sensor."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator)
'''
    SENSOR.write_text(text.rstrip() + addition + "\n", encoding="utf-8")


def patch_models() -> None:
    """Allow Power Down audit outcomes to be explicitly inconclusive."""
    text = MODELS.read_text(encoding="utf-8")
    text = text.replace(
        "    ev_successfully_blocked: bool = False\n",
        "    ev_successfully_blocked: bool | None = False\n",
        1,
    )
    text = text.replace(
        "    completed_successfully: bool = False\n",
        "    completed_successfully: bool | None = False\n",
        1,
    )
    MODELS.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_sensor()
    patch_models()
