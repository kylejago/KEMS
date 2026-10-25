"""Alpha9.141: correct scheduled overnight replacement costs, idle-budget truth."""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

KEMS = Path(__file__).resolve().parents[1] / "custom_components" / "kems"
NOW = datetime(2026, 10, 25, 15, 25, tzinfo=UTC)


def _extract(path: Path, names: set[str], namespace: dict):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert len(functions) == len(names)
    code = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *functions,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(code), str(path), "exec"), namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


def _tariff(rate_at_start=6.6, rate_at_midnight=6.6):
    changes = [
        SimpleNamespace(
            effective_from=date(2026, 10, 6),
            offpeak_rate_pence=rate_at_start,
            day_rate_pence=35.88,
            standing_charge_pence=55.52,
        ),
        SimpleNamespace(
            effective_from=date(2026, 10, 26),
            offpeak_rate_pence=rate_at_midnight,
            day_rate_pence=35.88,
            standing_charge_pence=55.52,
        ),
    ]
    return SimpleNamespace(
        offpeak_rate_pence=3.4933,
        day_rate_pence=28.3,
        standing_charge_pence=53.7,
        scheduled_changes=changes,
    )


def _floor():
    namespace = {
        "agile": SimpleNamespace(
            _next_cheap=lambda now, tariff: now.replace(hour=23, minute=30),
            BATTERY_WEAR_PENCE_PER_KWH=2.0,
        ),
        "effective_tariff_rates": None,
        "timedelta": timedelta,
    }
    tariff_module = _extract(
        KEMS / "tariff.py",
        {"effective_tariff_rates"},
        {
            "EffectiveTariffRates": SimpleNamespace,
        },
    )
    namespace["effective_tariff_rates"] = tariff_module.effective_tariff_rates
    return _extract(
        KEMS / "agile_forecast_arbitrage.py",
        {"_economic_export_floor_pence"},
        namespace,
    )._economic_export_floor_pence


def test_current_6_oct_tariff_replaces_expired_3_4933p_manual_rate():
    price = _floor()
    config = SimpleNamespace(charge_efficiency=0.95, discharge_efficiency=0.95)
    result = price(_tariff(), now=NOW, config=config)
    assert result == pytest.approx(6.6 / (0.95 * 0.95) + 2.0)
    assert result > 9.3
    assert result > 5.69
    assert result > 6.6
    assert result < 16.67


def test_midnight_rate_change_inside_cheap_window_is_conservative():
    result = _floor()(
        _tariff(rate_at_midnight=9.0),
        now=datetime(2026, 10, 25, 20, tzinfo=UTC),
        config=SimpleNamespace(charge_efficiency=0.95, discharge_efficiency=0.95),
    )
    assert result == pytest.approx(9.0 / (0.95 * 0.95) + 2.0)


def test_isolated_historical_helper_keeps_legacy_base_rate():
    result = _floor()(_tariff())
    assert result == pytest.approx(3.4933)


def _reconciler():
    return _extract(
        KEMS / "kems_core" / "agile_plan_budget_reconciliation.py",
        {"_number", "_current_slot_export_alignment", "reconcile_agile_budget"},
        {"datetime": datetime, "isfinite": __import__("math").isfinite},
    ).reconcile_agile_budget


def _plan():
    stamp = NOW.isoformat()
    return {
        "rolling_export_plan": {
            "available": True,
            "generated_at": stamp,
            "planned_battery_export_kwh": 31.787,
            "protected_house_energy_kwh": 13.897,
            "selected_slots": [],
            "required_in_current_slot_kwh": 0.0,
            "current_battery_export_target_kw": 0.0,
            "physical_planning_evidence": {"available": True},
            "physical_house_budget_evidence": {
                "available": True,
                "exportable_stored_kwh": 33.46,
                "exportable_ac_kwh": 31.787,
                "protected_house_stored_kwh": 13.897,
            },
        }
    }


def _guard():
    return {
        "status": "no_deliberate_export_requested",
        "requested_export_kw": 0.0,
        "permitted_export_kw": 0.0,
        "physical_energy_evidence": {"observed_at": NOW.isoformat()},
    }


def test_idle_guard_never_reports_a_nonexistent_physical_budget():
    result = _reconciler()(_plan(), _guard())
    assert result["status"] == "idle_no_export_requested"
    assert result["guard_budget_evaluated"] is False
    assert result["guard_exportable_physical_energy_kwh"] is None
    assert result["planner_verified_ac_export_budget_kwh"] == 31.787
    assert result["current_permitted_export_kw"] == 0.0


def test_active_export_missing_physical_budget_still_fails_closed():
    guard = _guard()
    guard.update(
        {
            "status": "physical_soc_reserve_protection",
            "requested_export_kw": 2.0,
            "permitted_export_kw": 1.0,
        }
    )
    result = _reconciler()(_plan(), guard)
    assert result["status"] == "unavailable"
    assert result["reason"] == "missing_or_invalid_energy_budget"


def test_idle_without_real_planner_evidence_is_not_misreported_as_healthy():
    plan = _plan()
    plan["rolling_export_plan"]["physical_house_budget_evidence"]["available"] = False
    result = _reconciler()(plan, _guard())
    assert result["status"] == "unavailable"
    assert result["reason"] == "idle_without_verified_planner_budget"


def test_mismatched_scan_cannot_claim_valid_guard_alignment():
    guard = _guard()
    guard["physical_energy_evidence"]["observed_at"] = (
        NOW - timedelta(minutes=1)
    ).isoformat()
    result = _reconciler()(_plan(), guard)
    assert result["status"] == "unavailable"
    assert result["reason"] == "planning_and_guard_not_from_same_scan"
