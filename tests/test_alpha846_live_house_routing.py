"""Regression coverage for Alpha8.46 live-house routing authority."""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "custom_components" / "kems" / "agile_solar_net_demand.py"


@dataclass(frozen=True)
class _Allocation:
    valid_from: datetime
    valid_to: datetime
    allocated_kwh: float


def _helpers() -> dict[str, Any]:
    """Load the pure routing helpers without importing the HA runtime chain."""
    tree = ast.parse(SOURCE.read_text())
    wanted = {
        "_number",
        "_dt",
        "_physical_house_kw",
        "_current_house_kw",
        "_current_physical_targets",
    }
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "math": math,
        "_EPSILON": 1e-6,
        "HARD_FLOOR_GUARD_MINUTES": 5.0,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, SOURCE.as_posix(), "exec"), namespace)
    return namespace


def _segment(start: datetime, *, solar_kw: float, battery_kw: float = 7.0):
    return {
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=5)).isoformat(),
        "solar_kw": solar_kw,
        "battery_kw": battery_kw,
    }


def test_future_capacity_and_current_house_authorities_are_separate() -> None:
    """Forecast capacity must not replace the current coordinator house load."""
    helpers = _helpers()
    owner = SimpleNamespace(
        _kems_solar_net_house_protection={"conservative_house_kw": 1.214},
        _panel_today_records=[SimpleNamespace(house_load_kw=1.315)],
    )

    assert helpers["_physical_house_kw"](owner) == 1.214
    assert helpers["_current_house_kw"](owner, fallback=1.214) == 1.315


def test_uploaded_0804_case_has_zero_avoidable_grid_import() -> None:
    """1.315kW house - 1.050kW solar must request 0.265kW from battery."""
    helpers = _helpers()
    target = helpers["_current_physical_targets"]
    start = datetime(2026, 8, 29, 7, 0, tzinfo=UTC)
    allocation = _Allocation(start, start + timedelta(minutes=30), 0.0)

    house, export, total = target(
        allocations=(allocation,),
        capacity_segments=[_segment(start, solar_kw=1.05)],
        now=start,
        house_kw=1.315,
        export_limit_kw=7.0,
        current_soc_percent=74.7,
        target_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )

    assert house == 0.265
    assert export == 0.0
    assert total == 0.265
    assert round(1.315 - 1.05 - house, 3) == 0.0


def test_load_spike_still_uses_battery_for_full_residual_house_load() -> None:
    """A high house load must not remain capped by a forecast-house surrogate."""
    helpers = _helpers()
    target = helpers["_current_physical_targets"]
    start = datetime(2026, 8, 29, 6, 55, tzinfo=UTC)

    house, export, total = target(
        allocations=(),
        capacity_segments=[_segment(start, solar_kw=1.0)],
        now=start,
        house_kw=6.6,
        export_limit_kw=7.0,
        current_soc_percent=80.0,
        target_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )

    assert house == 5.6
    assert export == 0.0
    assert total == 5.6


def test_current_routing_wiring_keeps_forecast_capacity_but_uses_live_house() -> None:
    """Static guard: future capacity and instantaneous routing have distinct inputs."""
    source = SOURCE.read_text()
    assert "future_house_kw = _physical_house_kw(self)" in source
    assert (
        "current_house_kw = _current_house_kw(self, fallback=future_house_kw)" in source
    )
    assert "house_kw=future_house_kw," in source
    assert "house_kw=current_house_kw," in source
    assert (
        'if mode in {"cheap_charge", "happy_hour_charge", "power_down_session"}'
        in source
    )
    assert 'if mode not in {"deadline_following", "maximum_discharge"}' in source
