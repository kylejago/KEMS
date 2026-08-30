"""Alpha8.56 regression for quantisation-sized daytime grid residuals."""

from __future__ import annotations

import ast
import importlib.util
import math
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).parents[1]
FLOW = ROOT / "custom_components" / "kems" / "agile_flow_presentation.py"
SLOT_FLOW = ROOT / "custom_components" / "kems" / "kems_core" / "slot_flow.py"


def _load_slot_flow_module():
    spec = importlib.util.spec_from_file_location("alpha856_slot_flow", SLOT_FLOW)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
        "_GRID_IMPORT_PRECISION_KWH": 0.001,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, FLOW.as_posix(), "exec"), namespace)
    return namespace["_future_today_projection"]


def _project(*, max_discharge_kw: float = 7.0):
    project = _projection_function()
    slot_start = datetime(2026, 8, 30, 10, 30, tzinfo=UTC)
    state = {
        "today_slots": [
            {
                "valid_from": slot_start.isoformat(),
                "valid_to": (slot_start + timedelta(minutes=30)).isoformat(),
                "rate_pence": 12.59,
                "planned_battery_to_home_kwh": 0.342,
                "rolling_planned_battery_export_kwh": 0.0,
                "battery_export_kwh": 0.0,
            }
        ],
        "current_routing_snapshot": {"simulated_soc_percent": 75.2},
    }
    config = SimpleNamespace(
        battery_capacity_kwh=56.42,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        battery_reserve_percent=10.0,
        max_discharge_kw=max_discharge_kw,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        max_charge_kw=7.0,
        site_import_limit_kw=None,
    )
    learned = SimpleNamespace(typical_house_load_kw=1.315)
    forecast = SimpleNamespace(
        hourly=[
            SimpleNamespace(
                timestamp=datetime(2026, 8, 30, 10, 0, tzinfo=UTC),
                solar_energy_kwh=0.63,
            )
        ]
    )
    forecast_plan = SimpleNamespace(
        minimum_precheap_soc_percent=10.0,
        maximum_overnight_soc_percent=100.0,
    )
    tariff = SimpleNamespace(offpeak_start=time(23, 30), offpeak_end=time(5, 30))
    owner = SimpleNamespace(
        _kems_solar_net_house_protection={"conservative_house_kw": 1.315}
    )
    output = project(
        owner,
        state,
        now=datetime(2026, 8, 30, 10, 0, tzinfo=UTC),
        config=config,
        learned=learned,
        forecast=forecast,
        forecast_plan=forecast_plan,
        tariff=tariff,
    )
    return output[slot_start.isoformat()]


def test_field_one_wh_residual_is_closed_with_available_battery_headroom() -> None:
    """The 11:30 field case must publish zero grid, not IMPORT 0.00 kWh."""
    projection = _project()
    assert projection["solar_to_home_kwh"] == pytest.approx(0.315)
    assert projection["battery_to_home_kwh"] == pytest.approx(0.3425)
    assert projection["grid_import_kwh"] == 0.0

    slot_flow = _load_slot_flow_module()
    published = slot_flow.build_slot_flow(**projection)
    assert published["flow_grid_action"] == "IDLE"
    assert published["flow_grid_import_kwh"] == 0.0
    assert published["flow_battery_action"] == "HOME"


def test_physical_discharge_limit_preserves_a_real_grid_shortfall() -> None:
    """Precision closure must never hide a genuinely capacity-limited deficit."""
    projection = _project(max_discharge_kw=0.6)
    assert projection["battery_to_home_kwh"] == pytest.approx(0.3)
    assert projection["grid_import_kwh"] == pytest.approx(0.0425)

    slot_flow = _load_slot_flow_module()
    published = slot_flow.build_slot_flow(**projection)
    assert published["flow_grid_action"] == "IMPORT"
    assert published["flow_grid_import_kwh"] == round(projection["grid_import_kwh"], 3)


def test_sub_wh_residual_is_not_closed_without_discharge_headroom() -> None:
    """Even a tiny residual remains real when the discharge limit is exhausted."""
    projection = _project(max_discharge_kw=0.684)
    assert projection["battery_to_home_kwh"] == pytest.approx(0.342)
    assert 0.0 < projection["grid_import_kwh"] <= 0.001
