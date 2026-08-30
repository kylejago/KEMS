"""Alpha8.57 regression for canonical house-first discharge reconciliation."""

from __future__ import annotations

import ast
import math
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).parents[1]
FLOW = ROOT / "custom_components" / "kems" / "agile_flow_presentation.py"


def _projection_function(*, cheap: bool = False):
    tree = ast.parse(FLOW.read_text())
    wanted = {
        "_number",
        "_dt",
        "_effective_battery_home",
        "_effective_battery_export",
        "_forecast_solar_kwh",
        "_best_future_rate",
        "_conservative_house_kw",
        "_close_home_precision_residual",
        "_future_today_projection",
    }
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    agile = SimpleNamespace(
        LONDON=ZoneInfo("Europe/London"),
        BATTERY_WEAR_PENCE_PER_KWH=2.0,
        _in_window=lambda *_args: cheap,
        _next_cheap=lambda now, _tariff: now + timedelta(hours=12),
    )
    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "timedelta": timedelta,
        "math": math,
        "agile": agile,
        "SimulationConfig": Any,
        "LearnedState": Any,
        "SolarForecastState": Any,
        "ForecastPlanState": Any,
        "TariffSettings": Any,
        "_EPSILON": 1e-6,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, FLOW.as_posix(), "exec"), namespace)
    return namespace["_future_today_projection"]


def _project(
    *,
    house_kw: float,
    solar_hour_kwh: float,
    planned_home_kwh: float,
    planned_export_kwh: float,
    max_discharge_kw: float = 7.0,
    inverter_limit_kw: float = 7.0,
    soc_percent: float = 78.0,
):
    project = _projection_function()
    slot_start = datetime(2026, 8, 30, 15, 0, tzinfo=UTC)
    state = {
        "today_slots": [
            {
                "valid_from": slot_start.isoformat(),
                "valid_to": (slot_start + timedelta(minutes=30)).isoformat(),
                "rate_pence": 19.51,
                "planned_battery_to_home_kwh": planned_home_kwh,
                "rolling_planned_battery_export_kwh": planned_export_kwh,
                "battery_export_kwh": planned_export_kwh,
            }
        ],
        "current_routing_snapshot": {"simulated_soc_percent": soc_percent},
    }
    config = SimpleNamespace(
        battery_capacity_kwh=56.42,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        battery_reserve_percent=10.0,
        max_discharge_kw=max_discharge_kw,
        inverter_limit_kw=inverter_limit_kw,
        export_limit_kw=7.0,
        max_charge_kw=7.0,
        site_import_limit_kw=None,
    )
    learned = SimpleNamespace(typical_house_load_kw=house_kw)
    forecast = SimpleNamespace(
        hourly=[
            SimpleNamespace(
                timestamp=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
                solar_energy_kwh=solar_hour_kwh,
            )
        ]
    )
    forecast_plan = SimpleNamespace(
        minimum_precheap_soc_percent=10.0,
        maximum_overnight_soc_percent=100.0,
    )
    tariff = SimpleNamespace(offpeak_start=time(23, 30), offpeak_end=time(5, 30))
    owner = SimpleNamespace(
        _kems_solar_net_house_protection={"conservative_house_kw": house_kw}
    )
    output = project(
        owner,
        state,
        now=datetime(2026, 8, 30, 14, 45, tzinfo=UTC),
        config=config,
        learned=learned,
        forecast=forecast,
        forecast_plan=forecast_plan,
        tariff=tariff,
    )
    return output[slot_start.isoformat()]


def test_field_export_slot_closes_multi_wh_house_residual_before_grid() -> None:
    """Reproduce the Alpha8.56 16:00 import/export field shape."""
    projection = _project(
        house_kw=1.466,
        solar_hour_kwh=0.772,
        planned_home_kwh=0.342,
        planned_export_kwh=2.767,
    )
    assert projection["solar_to_home_kwh"] == pytest.approx(0.386)
    assert projection["battery_to_home_kwh"] == pytest.approx(0.347)
    assert projection["battery_export_kwh"] == pytest.approx(2.767)
    assert projection["grid_import_kwh"] == 0.0


def test_house_wins_by_reducing_export_when_discharge_ceiling_is_full() -> None:
    """Discretionary export must be transferred to home before Grid import."""
    projection = _project(
        house_kw=1.6,
        solar_hour_kwh=0.0,
        planned_home_kwh=0.7,
        planned_export_kwh=2.8,
    )
    assert projection["battery_to_home_kwh"] == pytest.approx(0.8)
    assert projection["battery_export_kwh"] == pytest.approx(2.7)
    assert projection["grid_import_kwh"] == 0.0
    assert projection["battery_to_home_kwh"] + projection[
        "battery_export_kwh"
    ] == pytest.approx(3.5)


def test_real_physical_shortfall_imports_only_after_export_is_removed() -> None:
    """Grid remains valid only when the battery cannot physically cover the house."""
    projection = _project(
        house_kw=8.0,
        solar_hour_kwh=0.0,
        planned_home_kwh=0.5,
        planned_export_kwh=2.5,
    )
    assert projection["battery_to_home_kwh"] == pytest.approx(3.5)
    assert projection["battery_export_kwh"] == 0.0
    assert projection["grid_import_kwh"] == pytest.approx(0.5)
