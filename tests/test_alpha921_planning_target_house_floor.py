"""Regression proof for Alpha9.21 planning-target / house-floor separation."""

from __future__ import annotations

from datetime import UTC, datetime, time
from types import SimpleNamespace

import pytest

from custom_components.kems import agile_flow_presentation as flow
from custom_components.kems import agile_flow_reserve_policy as policy
from custom_components.kems.kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    SolarForecastState,
)
from custom_components.kems.tariff import TariffSettings


def _install_production_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install Alpha9.21 over the canonical projection without leaking globals."""
    base_projection = flow._future_today_projection
    base_close = flow._close_home_precision_residual
    if getattr(base_projection, "_kems_flow_reserve_policy", False):
        base_projection = policy._original_future_today_projection
        base_close = policy._original_close_home_precision_residual

    monkeypatch.setattr(flow, "_future_today_projection", base_projection)
    monkeypatch.setattr(flow, "_close_home_precision_residual", base_close)
    monkeypatch.setattr(policy, "_original_future_today_projection", None)
    monkeypatch.setattr(policy, "_original_close_home_precision_residual", None)
    policy.install_flow_reserve_policy()

    assert flow._future_today_projection is policy._future_today_projection_with_separate_reserves
    assert flow._close_home_precision_residual is policy._house_floor_close


def _project(
    *,
    soc_percent: float,
    planned_export_kwh: float = 0.0,
    hard_floor_latched: bool = False,
) -> dict[str, object]:
    """Run the real future-flow projection for one pre-cheap half hour."""
    start = datetime(2026, 9, 10, 21, 0, tzinfo=UTC)  # 22:00 BST
    end = datetime(2026, 9, 10, 21, 30, tzinfo=UTC)
    now = datetime(2026, 9, 10, 20, 59, tzinfo=UTC)
    state = {
        "today_slots": [
            {
                "valid_from": start.isoformat(),
                "valid_to": end.isoformat(),
                "rate_pence": 14.94,
                "planned_battery_to_home_kwh": 0.6,
                "rolling_planned_battery_export_kwh": planned_export_kwh,
            }
        ],
        "current_routing_snapshot": {"simulated_soc_percent": soc_percent},
        "rolling_export_plan": {
            "simulated_soc_percent": soc_percent,
            "hard_safety_floor_active": hard_floor_latched,
        },
    }
    config = SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=15.0,
        battery_initial_percent=soc_percent,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
    )
    learned = LearnedState(typical_house_load_kw=1.2)
    forecast = SolarForecastState(hourly=())
    forecast_plan = ForecastPlanState(
        minimum_precheap_soc_percent=15.0,
        maximum_overnight_soc_percent=100.0,
    )
    tariff = TariffSettings(
        mode="intelligent",
        day_rate_pence=28.3036,
        offpeak_rate_pence=3.4933,
        standing_charge_pence=53.70435,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
        intelligent_slots_enabled=True,
    )

    projection = flow._future_today_projection(
        SimpleNamespace(),
        state,
        now=now,
        config=config,
        learned=learned,
        forecast=forecast,
        forecast_plan=forecast_plan,
        tariff=tariff,
    )
    return projection[start.isoformat()]


def test_precheap_house_service_may_cross_15_without_expensive_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """15% stops export; it must not make Grid serve ordinary house demand."""
    _install_production_projection(monkeypatch)

    row = _project(soc_percent=14.5)

    assert row["battery_to_home_kwh"] == pytest.approx(0.6)
    assert row["grid_import_kwh"] == pytest.approx(0.0)
    assert 10.0 < row["estimated_soc_percent"] < 15.0
    assert row["planning_target_soc_percent"] == 15.0
    assert row["house_import_floor_soc_percent"] == 10.0
    assert row["hard_safety_recovery_soc_percent"] == 12.0
    assert row["planning_target_limits_export_only"] is True


def test_house_demand_crosses_15_before_any_deliberate_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """House-first discharge may cross 15%, but deliberate export may not."""
    _install_production_projection(monkeypatch)

    row = _project(soc_percent=16.0, planned_export_kwh=3.0)

    assert row["battery_to_home_kwh"] == pytest.approx(0.6)
    assert row["battery_export_kwh"] == pytest.approx(0.0)
    assert row["grid_import_kwh"] == pytest.approx(0.0)
    assert 10.0 < row["estimated_soc_percent"] < 15.0


def test_absolute_10_percent_floor_allows_grid_to_serve_house(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At the hard floor, battery-to-home stops and Grid may serve the house."""
    _install_production_projection(monkeypatch)

    row = _project(soc_percent=10.0)

    assert row["battery_to_home_kwh"] == pytest.approx(0.0)
    assert row["grid_import_kwh"] == pytest.approx(0.6)
    assert row["estimated_soc_percent"] == pytest.approx(10.0)


def test_12_percent_recovery_latch_remains_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted hard-floor latch suppresses discharge until recovery."""
    _install_production_projection(monkeypatch)

    row = _project(soc_percent=11.0, hard_floor_latched=True)

    assert row["hard_safety_floor_latched"] is True
    assert row["battery_to_home_kwh"] == pytest.approx(0.0)
    assert row["battery_export_kwh"] == pytest.approx(0.0)
    assert row["grid_import_kwh"] == pytest.approx(0.6)
    assert row["estimated_soc_percent"] == pytest.approx(11.0)
