from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1))


# 1. Home demand is mandatory before discretionary Agile export.  The total
# discharge budget still comes from the protected SOC floor, but the budget is
# spent chronologically on house demand before any remaining energy is ranked
# by export price.
replace_once(
    "custom_components/kems/kems_core/discharge_slot_ledger.py",
    '''    remaining = min(required, total_capacity)\n    if current is not None and remaining > _EPSILON:\n        forced = min(required_current, current_capacity, remaining)\n        current["allocation_kwh"] = forced\n        remaining -= forced\n\n    for item in sorted(\n        candidates,\n        key=lambda value: (-value["rate_pence"], value["valid_from"]),\n    ):\n        if remaining <= _EPSILON:\n            break\n        spare = max(item["total_capacity_kwh"] - item["allocation_kwh"], 0.0)\n        allocated = min(spare, remaining)\n        item["allocation_kwh"] += allocated\n        remaining -= allocated\n''',
    '''    remaining = min(required, total_capacity)\n\n    # Solar is already deducted when house_capacity_kwh is calculated. Spend\n    # the protected battery-discharge budget on the remaining house demand in\n    # chronological order before price-ranking any discretionary export. A\n    # price hold therefore means "do not export", never "buy premium grid\n    # energy while usable battery energy remains above the protected floor".\n    for item in sorted(candidates, key=lambda value: value["valid_from"]):\n        if remaining <= _EPSILON:\n            break\n        house_dispatch = min(\n            item["house_capacity_kwh"],\n            item["total_capacity_kwh"],\n            remaining,\n        )\n        item["allocation_kwh"] = house_dispatch\n        remaining -= house_dispatch\n\n    # Preserve the rolling deadline safety guard, but only with discharge\n    # budget left after mandatory home service. It may move discretionary\n    # discharge into the current slot; it may not displace future house energy\n    # and manufacture avoidable day-rate import.\n    if current is not None and remaining > _EPSILON:\n        required_extra = max(\n            required_current - current["allocation_kwh"],\n            0.0,\n        )\n        forced = min(\n            required_extra,\n            max(current_capacity - current["allocation_kwh"], 0.0),\n            remaining,\n        )\n        current["allocation_kwh"] += forced\n        remaining -= forced\n\n    # Only energy left after the household has been protected is discretionary\n    # export. Rank that remainder by Agile Outgoing price as before.\n    for item in sorted(\n        candidates,\n        key=lambda value: (-value["rate_pence"], value["valid_from"]),\n    ):\n        if remaining <= _EPSILON:\n            break\n        spare = max(item["total_capacity_kwh"] - item["allocation_kwh"], 0.0)\n        allocated = min(spare, remaining)\n        item["allocation_kwh"] += allocated\n        remaining -= allocated\n''',
)

# 2. Cheap-charge alignment must carry charge rather than replacing the
# canonical charge command with a stale rolling discharge target.
replace_once(
    "custom_components/kems/agile_control_alignment.py",
    '''    target_home = _number(plan.get("current_house_battery_kw"))\n    target_discharge = _number(plan.get("current_battery_discharge_target_kw"))\n    target_export = _number(plan.get("current_battery_export_target_kw"))\n    if target_home is None or target_discharge is None or target_export is None:\n        return None\n\n    target_home = max(target_home, 0.0)\n    target_export = max(target_export, 0.0)\n    target_discharge = max(target_discharge, target_home + target_export, 0.0)\n    return (\n        {\n            "battery_to_home_kw": target_home,\n            "battery_export_kw": target_export,\n            "total_discharge_kw": target_discharge,\n        },\n        plan,\n    )\n''',
    '''    dispatch_mode = str(plan.get("dispatch_mode") or "")\n    if dispatch_mode == "cheap_charge":\n        routing = agile_state.get("current_routing_snapshot")\n        charge = None\n        if isinstance(routing, dict) and routing.get("available"):\n            solar_charge = _number(routing.get("solar_to_battery_kw"))\n            grid_charge = _number(routing.get("grid_to_battery_kw"))\n            if solar_charge is not None or grid_charge is not None:\n                charge = max((solar_charge or 0.0) + (grid_charge or 0.0), 0.0)\n        if charge is None:\n            charge = max(\n                _number(simulation.current_simulated_battery_charge_power_kw) or 0.0,\n                0.0,\n            )\n        return (\n            {\n                "charge_kw": charge,\n                "battery_to_home_kw": 0.0,\n                "battery_export_kw": 0.0,\n                "total_discharge_kw": 0.0,\n            },\n            plan,\n        )\n\n    target_home = _number(plan.get("current_house_battery_kw"))\n    target_discharge = _number(plan.get("current_battery_discharge_target_kw"))\n    target_export = _number(plan.get("current_battery_export_target_kw"))\n    if target_home is None or target_discharge is None or target_export is None:\n        return None\n\n    target_home = max(target_home, 0.0)\n    target_export = max(target_export, 0.0)\n    target_discharge = max(target_discharge, target_home + target_export, 0.0)\n    return (\n        {\n            "charge_kw": 0.0,\n            "battery_to_home_kw": target_home,\n            "battery_export_kw": target_export,\n            "total_discharge_kw": target_discharge,\n        },\n        plan,\n    )\n''',
)
replace_once(
    "custom_components/kems/agile_control_alignment.py",
    '''    control_values.update(\n        {\n            "current_simulated_battery_to_home_power_kw": target["battery_to_home_kw"],\n            "current_simulated_battery_export_power_kw": target["battery_export_kw"],\n            "current_simulated_battery_power_kw": target["total_discharge_kw"],\n            "target_battery_export_power_kw": target["battery_export_kw"],\n        }\n    )\n''',
    '''    control_values.update(\n        {\n            "current_simulated_battery_charge_power_kw": target["charge_kw"],\n            "current_simulated_battery_to_home_power_kw": target["battery_to_home_kw"],\n            "current_simulated_battery_export_power_kw": target["battery_export_kw"],\n            "current_simulated_battery_power_kw": (\n                target["total_discharge_kw"] - target["charge_kw"]\n            ),\n            "target_battery_export_power_kw": target["battery_export_kw"],\n        }\n    )\n''',
)
replace_once(
    "custom_components/kems/agile_control_alignment.py",
    '''    target_within_limits = bool(\n        target["total_discharge_kw"] <= config.max_discharge_kw + 1e-6\n        and target["battery_export_kw"] <= config.export_limit_kw + 1e-6\n        and total_output <= config.inverter_limit_kw + 1e-6\n        and not control.site_import_limit_exceeded\n    )\n''',
    '''    target_within_limits = bool(\n        target["charge_kw"] <= config.max_charge_kw + 1e-6\n        and target["total_discharge_kw"] <= config.max_discharge_kw + 1e-6\n        and target["battery_export_kw"] <= config.export_limit_kw + 1e-6\n        and not (\n            target["charge_kw"] > 1e-6 and target["total_discharge_kw"] > 1e-6\n        )\n        and total_output <= config.inverter_limit_kw + 1e-6\n        and not control.site_import_limit_exceeded\n    )\n''',
)
replace_once(
    "custom_components/kems/agile_control_alignment.py",
    '''        desired_work_mode=(\n            "Feed-in First" if target["battery_export_kw"] > 0.01 else "Self Use"\n        ),\n        desired_charge_power_kw=0.0,\n        desired_battery_to_home_power_kw=round(target["battery_to_home_kw"], 3),\n''',
    '''        desired_work_mode=(\n            control.desired_work_mode\n            if target["charge_kw"] > 0.01\n            else (\n                "Feed-in First"\n                if target["battery_export_kw"] > 0.01\n                else "Self Use"\n            )\n        ),\n        desired_charge_power_kw=round(target["charge_kw"], 3),\n        desired_battery_to_home_power_kw=round(target["battery_to_home_kw"], 3),\n''',
)

# 3. Solar storage uses the marginal future slot after existing battery energy
# consumes the best future slots.  Compare direct export against net future value
# after both conversion losses and wear on the discharged kWh.
replace_once(
    "custom_components/kems/agile_smart_export.py",
    '''                best_future = _best_rate(\n                    rates,\n                    current.timestamp + timedelta(seconds=1),\n                    next_cheap,\n                )\n                stored_value = (\n                    best_future * config.charge_efficiency * config.discharge_efficiency\n                    - BATTERY_WEAR_PENCE_PER_KWH\n                )\n                if (\n                    solar_left\n                    and battery < capacity\n                    and (battery < floor or stored_value > rate + 0.001)\n                ):\n''',
    '''                future_exportable = max(battery - floor, 0.0) * max(\n                    config.discharge_efficiency,\n                    0.01,\n                )\n                potential_charge_input = min(\n                    solar_left,\n                    charge_limit,\n                    max(capacity - battery, 0.0)\n                    / max(config.charge_efficiency, 0.01),\n                )\n                potential_future_export = (\n                    potential_charge_input\n                    * max(config.charge_efficiency, 0.0)\n                    * max(config.discharge_efficiency, 0.0)\n                )\n                marginal_future = _threshold(\n                    rates,\n                    current.timestamp + timedelta(seconds=1),\n                    next_cheap,\n                    future_exportable + potential_future_export,\n                    max(config.max_discharge_kw, 0.0),\n                )\n                stored_value = _stored_solar_net_value_pence(\n                    marginal_future,\n                    config.charge_efficiency,\n                    config.discharge_efficiency,\n                )\n                if (\n                    solar_left\n                    and battery < capacity\n                    and (battery < floor or stored_value > rate + 0.001)\n                ):\n''',
)
replace_once(
    "custom_components/kems/agile_smart_export.py",
    '''\ndef _best_rate(\n    rates: list[AgileRate],\n    start: datetime,\n    end: datetime,\n) -> float:\n''',
    '''\ndef _stored_solar_net_value_pence(\n    future_rate_pence: float | None,\n    charge_efficiency: float,\n    discharge_efficiency: float,\n) -> float:\n    """Return net pence value of storing one input kWh of surplus solar."""\n    rate = max(float(future_rate_pence or 0.0), 0.0)\n    charge = min(max(float(charge_efficiency), 0.0), 1.0)\n    discharge = min(max(float(discharge_efficiency), 0.0), 1.0)\n    discharged_fraction = charge * discharge\n    return max(rate - BATTERY_WEAR_PENCE_PER_KWH, 0.0) * discharged_fraction\n\n\ndef _best_rate(\n    rates: list[AgileRate],\n    start: datetime,\n    end: datetime,\n) -> float:\n''',
)

replace_once(
    "custom_components/kems/manifest.json",
    '  "version": "0.8.0-alpha8.54"',
    '  "version": "0.8.0-alpha8.55"',
)

(ROOT / "docs/alpha8.55-release-notes.md").write_text(
    """# KEMS 0.8.0-alpha8.55\n\nAlpha8.55 is a simulation/planning/shadow parity correction driven by field evidence from 30 August 2026.\n\n## Changes\n\n- Makes the daytime house-routing invariant explicit outside confirmed cheap/Intelligent slots: solar serves the house first, then permissible battery discharge, and grid supplies only the physically unavoidable residual once the protected battery budget/headroom is exhausted.\n- Keeps deliberate Agile export subordinate to home demand. A low-price export hold no longer turns usable battery energy into premium-rate grid import.\n- Reconciles confirmed cheap-charge control/shadow targets with the canonical charging route so the shadow target carries charge power and zero battery discharge instead of an export-centric stale house-discharge target.\n- Values surplus-solar storage against the marginal future Agile slot after already-available battery energy has occupied the stronger slots. Charge efficiency, discharge efficiency and battery wear are included before choosing store-versus-export.\n\n## Protected boundaries\n\n- Power Down and Happy Hour priority are unchanged.\n- The 10% hard battery reserve and physical inverter/export/discharge limits remain authoritative.\n- Cheap/Intelligent charging policy is unchanged apart from shadow-target parity reporting.\n- EV policy is unchanged.\n- FoxESS commissioning state and all real hardware writes remain blocked.\n"""
)

(ROOT / "tests/test_alpha855_routing_economics_shadow.py").write_text(
    r'''"""Alpha8.55 regressions for home priority, cheap shadow parity and solar value."""

from __future__ import annotations

import ast
import importlib.util
import math
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
    spec = importlib.util.spec_from_file_location("alpha855_discharge_slot_ledger", LEDGER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
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


def test_grid_residual_only_appears_after_protected_battery_budget_is_exhausted() -> None:
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
    assert stored_value(marginal, 0.95, 0.95) == pytest.approx(13.130125)
    assert stored_value(marginal, 0.95, 0.95) < 14.28


def test_surplus_solar_stores_when_marginal_future_net_value_is_genuinely_higher() -> None:
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
    assert stored_value(marginal, 0.95, 0.95) == pytest.approx(18.8417)
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
    assert 'mode in {"cheap_charge", "happy_hour_charge", "power_down_session"}' in ledger_source
    assert '"hardware_writes": "blocked"' in ledger_source
    assert "commands_permitted=False" in alignment_source
    assert "real_backend_available=False" in alignment_source
'''
)
