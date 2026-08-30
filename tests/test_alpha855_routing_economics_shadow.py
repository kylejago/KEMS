"""Alpha8.55 regressions for home priority, cheap shadow parity and solar value."""

from __future__ import annotations

import ast
import importlib.util
import math
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
LEDGER = ROOT / "custom_components" / "kems" / "kems_core" / "discharge_slot_ledger.py"
ALIGNMENT = ROOT / "custom_components" / "kems" / "agile_control_alignment.py"
AGILE = ROOT / "custom_components" / "kems" / "agile_smart_export.py"


def _load_ledger_module():
    spec = importlib.util.spec_from_file_location(
        "alpha855_discharge_slot_ledger", LEDGER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _segment(start: datetime, *, battery_kw: float, solar_kw: float = 0.0):
    return {
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=30)).isoformat(),
        "battery_kw": battery_kw,
        "solar_kw": solar_kw,
    }


def _slot(start: datetime, rate: float):
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "rate_pence": rate,
    }


def test_future_hold_slots_serve_home_before_discretionary_export() -> None:
    """Low-price hold periods must use usable battery before premium grid."""
    ledger = _load_ledger_module()
    start = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
    starts = [start + timedelta(minutes=30 * offset) for offset in range(3)]
    plan = ledger.allocate_total_discharge_slots(
        slots=[
            _slot(starts[0], 13.33),
            _slot(starts[1], 22.88),
            _slot(starts[2], 13.94),
        ],
        capacity_segments=[_segment(item, battery_kw=2.0) for item in starts],
        now=start,
        deadline=start + timedelta(minutes=90),
        required_discharge_kwh=2.0,
        house_kw=1.0,
        export_limit_kw=2.0,
        safety_headroom_kwh=0.0,
    )

    first, peak, last = plan.allocations
    assert first.planned_house_battery_kwh == pytest.approx(0.5)
    assert first.planned_battery_export_kwh == 0.0
    assert last.planned_house_battery_kwh == pytest.approx(0.5)
    assert last.planned_battery_export_kwh == 0.0
    assert peak.planned_house_battery_kwh == pytest.approx(0.5)
    assert peak.planned_battery_export_kwh == pytest.approx(0.5)


def test_grid_residual_only_appears_after_protected_battery_budget_is_exhausted() -> (
    None
):
    """Chronological home service stops only when the SOC-protected budget ends."""
    ledger = _load_ledger_module()
    start = datetime(2026, 8, 30, 20, 30, tzinfo=UTC)
    starts = [start + timedelta(minutes=30 * offset) for offset in range(3)]
    plan = ledger.allocate_total_discharge_slots(
        slots=[_slot(item, 15.0 - offset) for offset, item in enumerate(starts)],
        capacity_segments=[_segment(item, battery_kw=2.0) for item in starts],
        now=start,
        deadline=start + timedelta(minutes=90),
        required_discharge_kwh=0.75,
        house_kw=1.0,
        export_limit_kw=2.0,
        safety_headroom_kwh=0.0,
    )

    first, second, third = plan.allocations
    assert first.planned_house_battery_kwh == pytest.approx(0.5)
    assert second.planned_house_battery_kwh == pytest.approx(0.25)
    assert third.planned_house_battery_kwh == 0.0
    assert sum(item.planned_battery_export_kwh for item in plan.allocations) == 0.0
    assert plan.allocated_total_discharge_kwh == pytest.approx(0.75)


@dataclass(frozen=True)
class _FakeControl:
    virtual_scenario_solar_power_kw: float = 0.0
    site_import_limit_exceeded: bool = False
    desired_min_soc_percent: float = 10.0
    plan_safe: bool = True
    blocked_reason: str = "Virtual backend only"
    desired_work_mode: str = "Force Charge"
    real_backend_available: bool = False
    commands_permitted: bool = False
    operating_reason: str = "base"
    desired_charge_power_kw: float = 7.0
    desired_battery_to_home_power_kw: float = 0.0
    desired_battery_export_power_kw: float = 0.0
    desired_total_discharge_power_kw: float = 0.0
    total_kh7_ac_output_kw: float = 0.0
    kh7_output_headroom_kw: float = 7.0
    next_action: str = "cheap charge"


def _alignment_functions():
    tree = ast.parse(ALIGNMENT.read_text())
    wanted = {"_number", "_rolling_target", "align_agile_control_state"}
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "ControlConfig": Any,
        "ControlState": Any,
        "SimulationState": Any,
        "replace": replace,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, ALIGNMENT.as_posix(), "exec"), namespace)
    return namespace["_rolling_target"], namespace["align_agile_control_state"]


def test_confirmed_cheap_charge_alignment_carries_charge_and_zero_discharge() -> None:
    """The 7 kW overnight outcome must be the shadow/control target too."""
    rolling_target, align = _alignment_functions()
    simulation = SimpleNamespace(
        saving_session_active=False,
        current_simulated_battery_charge_power_kw=7.0,
    )
    agile_state = {
        "current_action": "cheap overnight period — import / charge",
        "current_routing_snapshot": {
            "available": True,
            "solar_to_battery_kw": 0.0,
            "grid_to_battery_kw": 7.0,
        },
        "rolling_export_plan": {
            "available": True,
            "dispatch_mode": "cheap_charge",
            "dispatch_action": "cheap overnight period — import / charge",
            "target_soc_percent": 10.0,
            # Deliberately stale export-centric fields reproduce the field defect.
            "current_house_battery_kw": 1.185,
            "current_battery_export_target_kw": 0.0,
            "current_battery_discharge_target_kw": 1.185,
        },
    }

    target, _ = rolling_target(simulation, agile_state)
    assert target == {
        "charge_kw": 7.0,
        "battery_to_home_kw": 0.0,
        "battery_export_kw": 0.0,
        "total_discharge_kw": 0.0,
    }

    control = _FakeControl()
    config = SimpleNamespace(
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        export_limit_kw=7.0,
        inverter_limit_kw=7.0,
    )
    corrected = align(control, simulation, agile_state, config)
    assert corrected.desired_charge_power_kw == 7.0
    assert corrected.desired_battery_to_home_power_kw == 0.0
    assert corrected.desired_battery_export_power_kw == 0.0
    assert corrected.desired_total_discharge_power_kw == 0.0
    assert corrected.desired_work_mode == "Force Charge"
    assert corrected.commands_permitted is False
    assert corrected.real_backend_available is False


def _solar_value_helpers():
    tree = ast.parse(AGILE.read_text())
    wanted = {"_threshold", "_stored_solar_net_value_pence"}
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace: dict[str, Any] = {
        "AgileRate": Any,
        "UTC": UTC,
        "datetime": datetime,
        "math": math,
        "BATTERY_WEAR_PENCE_PER_KWH": 2.0,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, AGILE.as_posix(), "exec"), namespace)
    return namespace["_threshold"], namespace["_stored_solar_net_value_pence"]


@dataclass(frozen=True)
class _Rate:
    value_inc_vat: float
    valid_from: datetime


def test_surplus_solar_exports_now_when_marginal_future_net_value_is_lower() -> None:
    """14.28p now beats a 16.55p marginal future slot after losses and wear."""
    threshold, stored_value = _solar_value_helpers()
    start = datetime(2026, 8, 30, 8, 30, tzinfo=UTC)
    values = [22.88, 22.85, 21.82, 21.27, 16.55, 15.80]
    rates = [
        _Rate(value, start + timedelta(minutes=30 * (index + 1)))
        for index, value in enumerate(values)
    ]
    marginal = threshold(
        rates,
        start + timedelta(seconds=1),
        start + timedelta(hours=6),
        17.0,
        7.0,
    )
    assert marginal == 16.55
    assert stored_value(marginal, 0.95, 0.95) == pytest.approx(13.131375)
    assert stored_value(marginal, 0.95, 0.95) < 14.28


def test_surplus_solar_stores_when_marginal_future_net_value_is_genuinely_higher() -> (
    None
):
    """A still-unfilled 22.88p slot comfortably beats direct 14.28p export."""
    threshold, stored_value = _solar_value_helpers()
    start = datetime(2026, 8, 30, 8, 30, tzinfo=UTC)
    rates = [_Rate(22.88, start + timedelta(minutes=30))]
    marginal = threshold(
        rates,
        start + timedelta(seconds=1),
        start + timedelta(hours=1),
        3.5,
        7.0,
    )
    assert marginal == 22.88
    assert stored_value(marginal, 0.95, 0.95) == pytest.approx(18.8442)
    assert stored_value(marginal, 0.95, 0.95) > 14.28


def test_agile_day_uses_marginal_future_value_not_absolute_best_rate() -> None:
    """The live replay storage branch must use the same marginal-value contract."""
    source = AGILE.read_text()
    start = source.index("                future_exportable =")
    end = source.index("                inverter_used =", start)
    storage_branch = source[start:end]
    assert "marginal_future = _threshold(" in storage_branch
    assert "_stored_solar_net_value_pence(" in storage_branch
    assert "_best_rate(" not in storage_branch


def test_alpha855_keeps_special_dispatch_and_hardware_boundaries() -> None:
    ledger_source = (
        ROOT / "custom_components" / "kems" / "agile_total_discharge_ledger.py"
    ).read_text()
    alignment_source = ALIGNMENT.read_text()
    assert (
        'mode in {"cheap_charge", "happy_hour_charge", "power_down_session"}'
        in ledger_source
    )
    assert '"hardware_writes": "blocked"' in ledger_source
    assert "commands_permitted=False" in alignment_source
    assert "real_backend_available=False" in alignment_source
