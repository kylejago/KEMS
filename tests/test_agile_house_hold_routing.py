"""Regression coverage for independent house and Agile export battery targets."""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "custom_components" / "kems" / "agile_solar_net_demand.py"


@dataclass(frozen=True)
class _Allocation:
    valid_from: datetime
    valid_to: datetime
    allocated_kwh: float


def _target_function():
    """Load the pure target helper without importing the HA runtime chain."""
    tree = ast.parse(SOURCE.read_text())
    wanted = {"_number", "_dt", "_current_physical_targets"}
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
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, SOURCE.as_posix(), "exec"), namespace)
    return namespace["_current_physical_targets"]


def _segment(start: datetime, *, solar_kw: float, battery_kw: float) -> dict[str, Any]:
    return {
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=5)).isoformat(),
        "solar_kw": solar_kw,
        "battery_kw": battery_kw,
    }


def test_hold_export_slot_still_serves_house_from_battery() -> None:
    """A zero export allocation must not become premium-rate house import."""
    target = _target_function()
    start = datetime(2026, 8, 28, 8, 30, tzinfo=UTC)
    allocation = _Allocation(
        valid_from=start,
        valid_to=start + timedelta(minutes=30),
        allocated_kwh=0.0,
    )

    house, export, total = target(
        allocations=(allocation,),
        capacity_segments=[_segment(start, solar_kw=0.5, battery_kw=7.0)],
        now=start,
        house_kw=2.0,
        export_limit_kw=7.0,
    )

    assert house == 1.5
    assert export == 0.0
    assert total == 1.5


def test_house_target_survives_even_without_current_export_candidate() -> None:
    """House service is independent of whether the export allocator has a row."""
    target = _target_function()
    start = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)

    house, export, total = target(
        allocations=(),
        capacity_segments=[_segment(start, solar_kw=0.8, battery_kw=7.0)],
        now=start,
        house_kw=2.0,
        export_limit_kw=7.0,
    )

    assert house == 1.2
    assert export == 0.0
    assert total == 1.2


def test_selected_export_slot_preserves_existing_export_pacing() -> None:
    """A selected slot still adds paced export after serving the house first."""
    target = _target_function()
    start = datetime(2026, 8, 28, 9, 30, tzinfo=UTC)
    allocation = _Allocation(
        valid_from=start,
        valid_to=start + timedelta(minutes=30),
        allocated_kwh=1.0,
    )

    house, export, total = target(
        allocations=(allocation,),
        capacity_segments=[_segment(start, solar_kw=0.5, battery_kw=7.0)],
        now=start,
        house_kw=2.0,
        export_limit_kw=7.0,
    )

    assert house == 1.5
    assert export == 2.0
    assert total == 3.5


def test_cheap_and_priority_dispatch_modes_remain_outside_this_reconciliation() -> None:
    """The canonical guard must continue to leave special dispatch modes alone."""
    source = SOURCE.read_text()
    assert (
        'if mode in {"cheap_charge", "happy_hour_charge", "power_down_session"}'
        in source
    )
    assert 'if mode not in {"deadline_following", "maximum_discharge"}' in source
    assert (
        "cannot turn an otherwise avoidable house deficit into premium grid import"
        in source
    )
