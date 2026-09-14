"""Financial commissioning evidence plus retained-learning ROI projection."""

from __future__ import annotations

from contextvars import ContextVar
from datetime import date, datetime
from functools import wraps
from typing import Any

from .kems_core import LifetimeLedger, PeriodTotals, summarise_period_records

_CURRENT_FINANCIAL_PERIOD: ContextVar[PeriodTotals | None] = ContextVar(
    "kems_current_financial_period",
    default=None,
)
_INSTALLED = False

_FINANCIAL_ACTUAL_KEYS = (
    "actual_avoided_import_value_pence",
    "actual_system_value_pence",
)


def financial_period_from_records(
    daily_records: dict[str, dict[str, float]],
    *,
    tracking_date: date | None,
    tracking_values: dict[str, float] | None,
    commissioning_date: date | None,
    today: date,
) -> PeriodTotals:
    """Return retained physical/simulated evidence from financial start onward."""
    if commissioning_date is None or commissioning_date > today:
        return PeriodTotals(start_date=commissioning_date, end_date=today)

    records = dict(daily_records)
    if tracking_date == today and isinstance(tracking_values, dict):
        records[today.isoformat()] = dict(tracking_values)

    return summarise_period_records(
        records,
        commissioning_date,
        today,
        current_day=today,
    )


def roi_scoped_ledger(
    ledger: LifetimeLedger,
    period: PeriodTotals | None,
    *,
    commissioning_date: date | None,
    now: datetime,
) -> LifetimeLedger:
    """Scope actual payback while retaining the longer learning projection window.

    The retained pre-commission observation window is valuable evidence for the
    full KEMS proposal projection, especially during the first days after the
    physical system goes live.  Actual payback is different: it must start at the
    explicitly selected financial commissioning date.  Keep those two contracts
    separate by replacing only the actual-value counters and operating-day count
    from the financial period while leaving first_observation and all simulated
    proposal evidence untouched.
    """
    if (
        commissioning_date is None
        or now.date() < commissioning_date
        or period is None
        or period.start_date != commissioning_date
        or period.end_date != now.date()
    ):
        return ledger

    scoped = LifetimeLedger.from_dict(ledger.to_dict())
    for key in _FINANCIAL_ACTUAL_KEYS:
        setattr(scoped, key, float(getattr(period, key, 0.0)))
    scoped.system_operating_days = period.days_included
    return scoped


def _financial_metric(data: Any, key: str) -> float | None:
    """Return one financial-period value from the coordinator payload."""
    period = data.periods.get("financial")
    if period is None or period.start_date is None:
        return None
    return float(getattr(period, key, 0.0))


def _financial_gbp(data: Any, key: str) -> float | None:
    """Return one financial-period pence value converted to GBP."""
    value = _financial_metric(data, key)
    return None if value is None else round(value / 100, 2)


def install_financial_roi_scope() -> None:
    """Install the isolated financial-scope extensions once."""
    global _INSTALLED
    if _INSTALLED:
        return

    from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
    from homeassistant.const import UnitOfEnergy

    from . import lifetime as lifetime_module
    from . import sensor as sensor_module
    from .kems_core.roi import ROIEngine

    original_period_summaries = lifetime_module.LifetimeLedgerRecorder.period_summaries

    @wraps(original_period_summaries)
    def period_summaries(self: Any, now: datetime) -> dict[str, PeriodTotals]:
        summaries = original_period_summaries(self, now)
        financial = financial_period_from_records(
            self._daily_records,
            tracking_date=self._tracking_date,
            tracking_values=self._tracking_values,
            commissioning_date=self._ledger.commissioning_date,
            today=now.date(),
        )
        summaries["financial"] = financial
        _CURRENT_FINANCIAL_PERIOD.set(financial)
        return summaries

    lifetime_module.LifetimeLedgerRecorder.period_summaries = period_summaries

    original_evaluate = ROIEngine.evaluate

    @wraps(original_evaluate)
    def evaluate(
        self: Any,
        ledger: LifetimeLedger,
        simulation: Any,
        now: datetime,
        config: Any,
    ) -> Any:
        financial = _CURRENT_FINANCIAL_PERIOD.get()
        scoped = roi_scoped_ledger(
            ledger,
            financial,
            commissioning_date=config.commissioning_date,
            now=now,
        )
        return original_evaluate(self, scoped, simulation, now, config)

    ROIEngine.evaluate = evaluate

    existing_keys = {description.key for description in sensor_module.SENSORS}
    descriptions = (
        sensor_module.KEMSSensorEntityDescription(
            key="financial_commissioning_date",
            name="Financial commissioning date",
            icon="mdi:calendar-start",
            device_class=SensorDeviceClass.DATE,
            value_fn=lambda data: data.lifetime.commissioning_date,
        ),
        sensor_module.KEMSSensorEntityDescription(
            key="financial_house_consumption",
            name="House electricity since commissioning",
            icon="mdi:home-lightning-bolt",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL,
            suggested_display_precision=2,
            value_fn=lambda data: _financial_metric(data, "house_consumption_kwh"),
        ),
        sensor_module.KEMSSensorEntityDescription(
            key="financial_grid_import",
            name="Grid import since commissioning",
            icon="mdi:transmission-tower-import",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL,
            suggested_display_precision=2,
            value_fn=lambda data: _financial_metric(data, "grid_import_kwh"),
        ),
        sensor_module.KEMSSensorEntityDescription(
            key="financial_grid_export",
            name="Grid export since commissioning",
            icon="mdi:transmission-tower-export",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL,
            suggested_display_precision=2,
            value_fn=lambda data: _financial_metric(data, "grid_export_kwh"),
        ),
        sensor_module.KEMSSensorEntityDescription(
            key="financial_solar_generation",
            name="Solar generation since commissioning",
            icon="mdi:solar-power",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL,
            suggested_display_precision=2,
            value_fn=lambda data: _financial_metric(data, "solar_generation_kwh"),
        ),
        sensor_module.KEMSSensorEntityDescription(
            key="financial_export_income",
            name="Paid export income since commissioning",
            icon="mdi:cash-plus",
            device_class=SensorDeviceClass.MONETARY,
            native_unit_of_measurement="GBP",
            state_class=SensorStateClass.TOTAL,
            suggested_display_precision=2,
            value_fn=lambda data: _financial_gbp(data, "export_income_pence"),
        ),
    )
    sensor_module.SENSORS = (
        *sensor_module.SENSORS,
        *(
            description
            for description in descriptions
            if description.key not in existing_keys
        ),
    )

    _INSTALLED = True
