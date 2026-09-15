"""Regression coverage for Alpha9.43 Full KEMS export observability."""

from __future__ import annotations

from datetime import UTC, date, datetime

from custom_components.kems.kems_core import (
    ScenarioComparisonState,
    ScenarioPeriodComparison,
    ScenarioSummary,
)
from custom_components.kems.kems_core.observability import (
    full_kems_battery_export_enabled,
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


def test_full_kems_export_sensor_uses_customer_digital_twin_authority() -> None:
    """A ready Full KEMS model exposes battery export regardless of live policy."""
    scenarios = _scenarios(
        ScenarioSummary(
            key="kems_full",
            label="Full KEMS smart control",
            ready=True,
            battery_export_kwh=17.035,
            current_battery_export_kw=0.0,
        )
    )

    assert full_kems_battery_export_enabled(scenarios) is True


def test_full_kems_export_sensor_is_unavailable_until_full_kems_is_ready() -> None:
    """Do not claim Full KEMS export capability until that model is ready."""
    scenarios = _scenarios(
        ScenarioSummary(
            key="kems_full",
            label="Full KEMS smart control",
            ready=False,
        )
    )

    assert full_kems_battery_export_enabled(scenarios) is None
