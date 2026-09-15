"""Regression coverage for Alpha9.43 Full KEMS export observability."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from custom_components.kems.binary_sensor import BINARY_SENSORS
from custom_components.kems.kems_core import (
    ScenarioComparisonState,
    ScenarioPeriodComparison,
    ScenarioSummary,
)


def _scenarios(*summaries: ScenarioSummary) -> ScenarioComparisonState:
    return ScenarioComparisonState(
        generated_at=datetime(2026, 9, 15, 15, 30, tzinfo=UTC),
        periods={
            "today": ScenarioPeriodComparison(
                key="today",
                label="Today",
                start_date=date(2026, 9, 15),
                end_date=date(2026, 9, 15),
                days_included=1,
                scenarios=tuple(summaries),
            )
        },
    )


def _battery_export_description():
    return next(
        item for item in BINARY_SENSORS if item.key == "battery_export_simulated"
    )


def test_full_kems_export_sensor_uses_customer_digital_twin_authority() -> None:
    """Live no-export policy must not make the Full KEMS capability look disabled."""
    data = SimpleNamespace(
        simulation=SimpleNamespace(
            battery_export_enabled=False,
            no_export_mode_active=True,
            export_tariff_active=False,
        ),
        scenarios=_scenarios(
            ScenarioSummary(
                key="kems_full",
                label="Full KEMS smart control",
                ready=True,
                battery_export_kwh=17.035,
                current_battery_export_kw=0.0,
            )
        ),
    )

    assert _battery_export_description().is_on_fn(data) is True


def test_full_kems_export_sensor_is_unavailable_until_full_kems_is_ready() -> None:
    """Do not fall back to the live/base export permission before Full KEMS is ready."""
    data = SimpleNamespace(
        simulation=SimpleNamespace(
            battery_export_enabled=True,
            no_export_mode_active=False,
            export_tariff_active=True,
        ),
        scenarios=_scenarios(
            ScenarioSummary(
                key="kems_full",
                label="Full KEMS smart control",
                ready=False,
            )
        ),
    )

    assert _battery_export_description().is_on_fn(data) is None
