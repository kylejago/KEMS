from pathlib import Path

flow_path = Path("custom_components/kems/agile_flow_presentation.py")
text = flow_path.read_text()

old = "_EPSILON = 1e-6\n"
new = "_EPSILON = 1e-6\n_GRID_IMPORT_PRECISION_KWH = 0.001\n"
assert old in text
text = text.replace(old, new, 1)

anchor = "def _future_today_projection(\n"
helper = '''def _close_home_precision_residual(
    *,
    remaining_house_kwh: float,
    battery_home_kwh: float,
    battery_energy_kwh: float,
    floor_kwh: float,
    discharge_limit_kwh: float,
    discharge_efficiency: float,
) -> float:
    """Close only quantisation-sized home residuals with usable battery."""
    remaining_house = max(remaining_house_kwh, 0.0)
    battery_home = min(max(battery_home_kwh, 0.0), remaining_house)
    residual = max(remaining_house - battery_home, 0.0)
    if residual <= _EPSILON or residual > _GRID_IMPORT_PRECISION_KWH + _EPSILON:
        return battery_home

    discharge_headroom = max(discharge_limit_kwh - battery_home, 0.0)
    battery_headroom = max(
        (battery_energy_kwh - floor_kwh) * max(discharge_efficiency, 0.01),
        0.0,
    )
    if min(discharge_headroom, battery_headroom) + _EPSILON < residual:
        return battery_home
    return remaining_house


'''
assert anchor in text
text = text.replace(anchor, helper + anchor, 1)

old_block = '''        else:
            solar_home = min(solar_generation, house, inverter_limit)
            remaining_house = max(house - solar_home, 0.0)
            battery_home = min(battery_home, remaining_house)
            battery -= battery_home / discharge_efficiency
            solar_left = max(solar_generation - solar_home, 0.0)
            best_future = _best_future_rate(slots, start, deadline)
            stored_value = (
                best_future * charge_efficiency * discharge_efficiency
                - agile.BATTERY_WEAR_PENCE_PER_KWH
            )
            floor_kwh = capacity * precheap_target / 100.0
            if (
'''
new_block = '''        else:
            solar_home = min(solar_generation, house, inverter_limit)
            remaining_house = max(house - solar_home, 0.0)
            floor_kwh = capacity * precheap_target / 100.0
            battery_home = min(battery_home, remaining_house)
            battery_home = _close_home_precision_residual(
                remaining_house_kwh=remaining_house,
                battery_home_kwh=battery_home,
                battery_energy_kwh=battery,
                floor_kwh=floor_kwh,
                discharge_limit_kwh=min(
                    discharge_limit,
                    max(inverter_limit - solar_home, 0.0),
                ),
                discharge_efficiency=discharge_efficiency,
            )
            battery -= battery_home / discharge_efficiency
            solar_left = max(solar_generation - solar_home, 0.0)
            best_future = _best_future_rate(slots, start, deadline)
            stored_value = (
                best_future * charge_efficiency * discharge_efficiency
                - agile.BATTERY_WEAR_PENCE_PER_KWH
            )
            if (
'''
assert old_block in text
text = text.replace(old_block, new_block, 1)
flow_path.write_text(text)

manifest = Path("custom_components/kems/manifest.json")
manifest_text = manifest.read_text()
assert '"version": "0.8.0-alpha8.55"' in manifest_text
manifest.write_text(
    manifest_text.replace(
        '"version": "0.8.0-alpha8.55"',
        '"version": "0.8.0-alpha8.56"',
        1,
    )
)

test = '''"""Alpha8.56 regression for quantisation-sized daytime grid residuals."""

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
    assert published["flow_grid_import_kwh"] == pytest.approx(0.043)


def test_sub_wh_residual_is_not_closed_without_discharge_headroom() -> None:
    """Even a tiny residual remains real when the discharge limit is exhausted."""
    projection = _project(max_discharge_kw=0.684)
    assert projection["battery_to_home_kwh"] == pytest.approx(0.342)
    assert 0.0 < projection["grid_import_kwh"] <= 0.001
'''
Path("tests/test_alpha856_grid_precision.py").write_text(test)

notes = '''# KEMS 0.8.0-alpha8.56

Alpha8.56 is a narrowly bounded canonical flow-precision correction following Alpha8.55 field proof.

## Changed

- Close only quantisation-sized (<= 0.001 kWh) future daytime home-demand residuals with battery-to-home when the battery is above the protected floor and both discharge and shared-inverter headroom can physically supply the remainder.
- Publish exactly zero grid import for that case, preventing a mathematically insignificant 1 Wh remainder from appearing as `IMPORT · 0.00 kWh`.
- Preserve genuine grid residuals whenever the physical discharge/inverter/SOC headroom cannot cover them.

## Field regression

The regression reproduces the 30 Aug 11:30 slot: 1.315 kW conservative house demand over a half-hour, 0.315 kWh solar-to-home, 0.342 kWh rounded planned battery-to-home and ample battery headroom. The canonical projection closes the approximately 0.0005 kWh quantisation remainder with battery-to-home and publishes Grid IDLE / 0.000 kWh.

## Protected boundaries

No export ranking, solar storage economics, reserve policy, Power Down, Happy Hour, EV policy, cheap-window routing, FoxESS commissioning or real hardware writes are changed. Real hardware writes remain blocked.
'''
Path("docs/alpha8.56-release-notes.md").write_text(notes)

Path("scripts/apply_alpha856.py").unlink()
Path(".github/workflows/apply-alpha856.yml").unlink()
