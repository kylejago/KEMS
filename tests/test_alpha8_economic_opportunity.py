"""Alpha8 contracts for canonical Agile economic-opportunity ownership."""

from __future__ import annotations

import ast
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
COMPAT = KEMS / "agile_alpha7_compat.py"
FACADE = KEMS / "agile_economic_opportunity.py"
RUNTIME = KEMS / "agile_economic_opportunity_runtime.py"
DASHBOARD_RUNTIME = KEMS / "dashboard_economic_opportunity_runtime.py"
HISTORICAL_RUNTIME = KEMS / "agile_alpha740_opportunity_guard.py"
HISTORICAL_DASHBOARD = KEMS / "dashboard_alpha740_agile_primary.py"


def _compat_specs() -> list[tuple[str, str]]:
    tree = ast.parse(COMPAT.read_text(encoding="utf-8"))
    specs: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id not in {"PRE_BASE_PATCHES", "POST_BASE_PATCHES"}:
            continue
        assert isinstance(node.value, ast.Tuple)
        for item in node.value.elts:
            assert isinstance(item, ast.Tuple) and len(item.elts) == 2
            specs.append(
                (ast.literal_eval(item.elts[0]), ast.literal_eval(item.elts[1]))
            )
    return specs


def _load_economic_guard():
    tree = ast.parse(RUNTIME.read_text(encoding="utf-8"))
    function_names = {
        "_number",
        "_dt",
        "_current_slot",
        "_remaining_hours",
        "_economic_guard",
    }
    constant_names = {
        "_EPSILON",
        "PRICE_ADVANTAGE_PENCE",
        "UNCERTAINTY_MARGIN_FRACTION",
    }
    body: list[ast.stmt] = []
    for node in tree.body:
        constant = isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in constant_names
            for target in node.targets
        )
        helper = isinstance(node, ast.FunctionDef) and node.name in function_names
        if constant or helper:
            body.append(node)

    namespace = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "math": math,
    }
    isolated = ast.Module(body=body, type_ignores=[])
    exec(
        compile(ast.fix_missing_locations(isolated), str(RUNTIME), "exec"),
        namespace,
    )
    return namespace["_economic_guard"]


def _slot(start: datetime, rate: float) -> dict[str, object]:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "rate_pence": rate,
    }


def test_economic_opportunity_retires_both_alpha740_modules_from_execution() -> None:
    specs = _compat_specs()
    previous = ("agile_product_presentation", "install_product_presentation")
    canonical = ("agile_economic_opportunity", "install_economic_opportunity")
    following = ("agile_price_publication", "install_price_publication")

    assert specs.index(canonical) > specs.index(previous)
    assert specs.index(canonical) < specs.index(following)
    assert not any(
        module_name
        in {"agile_alpha740_opportunity_guard", "dashboard_alpha740_agile_primary"}
        for module_name, _ in specs
    )
    assert HISTORICAL_RUNTIME.is_file()
    assert HISTORICAL_DASHBOARD.is_file()


def test_economic_opportunity_runtime_owners_are_byte_identical_to_alpha740() -> None:
    assert RUNTIME.read_bytes() == HISTORICAL_RUNTIME.read_bytes()
    assert DASHBOARD_RUNTIME.read_bytes() == HISTORICAL_DASHBOARD.read_bytes()


def test_economic_opportunity_facade_preserves_planning_then_dashboard_order() -> None:
    source = FACADE.read_text(encoding="utf-8")
    ast.parse(source)

    planning_call = "opportunity_runtime.install_alpha740_opportunity_guard_patch()"
    dashboard_call = (
        "dashboard_runtime.install_alpha740_agile_primary_dashboard_patch()"
    )
    assert planning_call in source
    assert dashboard_call in source
    assert source.index(planning_call) < source.index(dashboard_call)
    assert "agile_alpha740_opportunity_guard" not in source
    assert "dashboard_alpha740_agile_primary" not in source


def test_better_current_slot_gets_proactive_export_floor() -> None:
    economic_guard = _load_economic_guard()
    now = datetime(2026, 8, 20, 14, 10, tzinfo=UTC)
    state = {
        "today_slots": [
            _slot(now.replace(minute=0), 12.27),
            _slot(now.replace(minute=30), 11.95),
            _slot(now.replace(hour=15, minute=0), 10.20),
        ]
    }
    plan = {
        "exportable_battery_energy_kwh": 4.0,
        "planned_battery_export_kwh": 4.0,
    }

    guard = economic_guard(state, plan, now=now, effective_kw=7.0)

    assert guard["active"] is True
    assert guard["current_rate_pence"] == 12.27
    assert guard["price_advantage_pence"] > 0
    assert guard["minimum_current_export_kwh"] > 0


def test_worse_current_slot_does_not_preempt_better_future_slots() -> None:
    economic_guard = _load_economic_guard()
    now = datetime(2026, 8, 20, 14, 10, tzinfo=UTC)
    state = {
        "today_slots": [
            _slot(now.replace(minute=0), 8.0),
            _slot(now.replace(minute=30), 12.0),
            _slot(now.replace(hour=15, minute=0), 11.0),
        ]
    }
    plan = {
        "exportable_battery_energy_kwh": 2.0,
        "planned_battery_export_kwh": 2.0,
    }

    guard = economic_guard(state, plan, now=now, effective_kw=7.0)

    assert guard["active"] is False
    assert guard["minimum_current_export_kwh"] == 0


def test_economic_opportunity_preserves_deadline_modes_and_power_clamps() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert 'if mode in {"maximum_discharge", "target_reached"}:' in source
    assert "return targets" in source
    assert "max(config.export_limit_kw, 0.0)" in source
    assert "max(config.inverter_limit_kw - house_kw, 0.0)" in source
    assert "max(config.max_discharge_kw - house_kw, 0.0)" in source
    assert "total_kw = min(house_kw + export_kw, effective_kw)" in source
    assert "never weakens the 10% SOC floor" in source


def test_economic_opportunity_keeps_plan_evidence_and_dashboard_contract() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    dashboard = DASHBOARD_RUNTIME.read_text(encoding="utf-8")

    assert 'plan["economic_opportunity_guard"] = guard' in runtime
    assert 'plan["economic_guard_active"] = bool(guard.get("active"))' in runtime
    assert "Full KEMS Agile — command centre" in dashboard
    assert "Economic early-export guard" in dashboard
    assert "Overall strategy comparison — which KEMS type is winning?" in dashboard
    assert "Strategy evidence by period" in dashboard


def test_economic_opportunity_cannot_enable_real_hardware_writes() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (FACADE, RUNTIME, DASHBOARD_RUNTIME)
    )

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "real FoxESS hardware writes remain blocked" in source.replace("\n", " ")
