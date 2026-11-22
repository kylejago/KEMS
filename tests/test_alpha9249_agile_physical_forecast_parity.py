"""Alpha9.249: physical Agile display parity without changing dispatch authority."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
FLOW = KEMS / "agile_flow_presentation.py"
CONTINUITY = KEMS / "agile_live_solar_soc_continuity.py"
DASHBOARD = KEMS / "kems_master_dashboard.yaml"
NOW = datetime(2026, 11, 22, 13, 47, 37, tzinfo=UTC)
CAPACITY = 49.28
LOWER_KWH = 43.019


def _dt(value):
    try:
        value = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    return value.astimezone(UTC) if value.tzinfo is not None else None


def _number(value):
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _fn(path: Path, name: str, namespace: dict[str, Any]):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    func = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    module = ast.Module(body=[func], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


def _plan():
    return {
        "generated_at": NOW.isoformat(),
        "simulated_soc_percent": 59.2,
        "physical_planning_evidence": {
            "available": True,
            "physical_samples": 25,
            "physical_energy_lower_bound_kwh": LOWER_KWH,
            "planning_soc_percent": 87.294,
            "independent_digital_twin_soc_percent": 59.2,
        },
    }


def _slots():
    # Real user 13:47 example: house 1.5–1.6 kWh per full slot,
    # and an independent 1.862 kWh export allocation at peak prices.
    result = []
    start = NOW.replace(minute=30, second=0)
    for i in range(20):
        a = start + timedelta(minutes=30 * i)
        b = a + timedelta(minutes=30)
        export = 1.862 if 5 <= i <= 12 else 0.0
        house = 1.638 if i > 0 else 0.639
        result.append(
            {
                "valid_from": a.isoformat(),
                "valid_to": b.isoformat(),
                "label": a.strftime("%H:%M"),
                "rate_pence": 26.6 if export else 17.3,
                "planned_battery_to_home_kwh": house,
                "rolling_planned_battery_export_kwh": export,
                "planned_total_battery_discharge_kwh": house + export,
            }
        )
    return result


def _projection(state):
    fake_agile = SimpleNamespace(
        LONDON=ZoneInfo("Europe/London"),
        BATTERY_WEAR_PENCE_PER_KWH=1.0,
        _next_cheap=lambda now, tariff: now.replace(hour=23, minute=30, second=0),
        _in_window=lambda *args: False,
    )

    # Real separate-reserve wrapper already injects the 10% floor into
    # the home precision helper while preserving the 15% export reserve.
    def house_helper(**kw):
        return min(
            max(kw["remaining_house_kwh"], 0.0),
            max(
                (kw["battery_energy_kwh"] - CAPACITY * 0.10)
                * kw["discharge_efficiency"],
                0.0,
            ),
            kw["discharge_limit_kwh"],
        )

    ns = {
        "Any": Any,
        "datetime": datetime,
        "UTC": UTC,
        "SimulationConfig": Any,
        "LearnedState": Any,
        "SolarForecastState": Any,
        "ForecastPlanState": Any,
        "TariffSettings": Any,
        "agile": fake_agile,
        "_number": _number,
        "_dt": _dt,
        "_EPSILON": 1e-6,
        "_conservative_house_kw": lambda *args: 3.276,
        "_effective_battery_home": lambda slot, **kw: slot.get(
            "planned_battery_to_home_kwh", 0.0
        ),
        "_effective_battery_export": lambda slot, **kw: slot.get(
            "rolling_planned_battery_export_kwh", 0.0
        ),
        "_forecast_solar_kwh": lambda *args: 0.0,
        "_best_future_rate": lambda *args: 26.6,
        "_close_home_precision_residual": house_helper,
    }
    fn = _fn(FLOW, "_future_today_projection", ns)
    config = SimpleNamespace(
        battery_capacity_kwh=CAPACITY,
        battery_reserve_percent=10.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        site_import_limit_kw=14.5,
    )
    learned = SimpleNamespace()
    forecast = SimpleNamespace()
    forecast_plan = SimpleNamespace(
        minimum_precheap_soc_percent=15.0,
        maximum_overnight_soc_percent=100.0,
    )
    return fn(
        object(),
        state,
        now=NOW,
        config=config,
        learned=learned,
        forecast=forecast,
        forecast_plan=forecast_plan,
        tariff=SimpleNamespace(offpeak_start=time(23, 30), offpeak_end=time(5, 30)),
    )


def test_live_forecast_prefers_verified_physical_not_59_percent_twin():
    state = {
        "today_slots": _slots(),
        "rolling_export_plan": _plan(),
        "current_routing_snapshot": {"simulated_soc_percent": 59.2},
    }
    future = _projection(state)
    first_peak = future["2026-11-22T16:00:00+00:00"]
    assert first_peak["battery_export_kwh"] == pytest.approx(1.862)
    assert first_peak["battery_to_home_kwh"] > 1.5
    assert first_peak["estimated_soc_percent"] > 50
    assert "verified FoxESS physical lower-bound" in first_peak["basis"]
    # A physical flow forecast is presentation-only; no rolling plan changes.
    assert state["rolling_export_plan"]["simulated_soc_percent"] == 59.2
    assert state["rolling_export_plan"]["physical_planning_evidence"]["available"]


def test_export_stops_at_fifteen_but_house_can_continue_to_ten():
    state = {
        "today_slots": _slots(),
        "rolling_export_plan": _plan(),
        "current_routing_snapshot": {"simulated_soc_percent": 59.2},
    }
    future = _projection(state)
    rows = list(future.values())
    assert rows
    assert all(row["estimated_soc_percent"] >= 10.0 - 0.00001 for row in rows)
    assert any(
        row["battery_to_home_kwh"] > 0
        and row["estimated_soc_percent"] < 15.0
        and row["battery_export_kwh"] == pytest.approx(0.0)
        for row in rows
    )
    # Export cannot be allocated from a slot which has fallen below 15%.
    for row in rows:
        if row["battery_export_kwh"] > 0.001:
            assert row["estimated_soc_percent"] >= 15.0 - 0.00001
    assert rows[-1]["estimated_soc_percent"] >= 10.0


def test_unverified_or_old_physical_proof_cannot_promote_twin_to_physical():
    state = {
        "today_slots": _slots(),
        "rolling_export_plan": _plan(),
        "current_routing_snapshot": {"simulated_soc_percent": 59.2},
    }
    for change in (
        lambda p: p["physical_planning_evidence"].update({"physical_samples": 1}),
        lambda p: p.update({"generated_at": (NOW - timedelta(minutes=5)).isoformat()}),
        lambda p: p["physical_planning_evidence"].update({"available": False}),
    ):
        plan = _plan()
        change(plan)
        state["rolling_export_plan"] = plan
        result = _projection(state)
        assert "verified FoxESS" not in result[_slots()[5]["valid_from"]]["basis"]


def test_rebase_prefers_same_scan_physical_soc_and_keeps_twin_auditable():
    ns = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "_number": _number,
        "_dt": _dt,
        "_EPSILON": 1e-6,
        "SimulationConfig": Any,
    }
    _fn(CONTINUITY, "_clamp", ns)
    _fn(CONTINUITY, "_battery_delta_kwh", ns)
    rebase = _fn(CONTINUITY, "_rebase_display_soc", ns)
    today = [
        {
            "valid_from": "2026-11-22T13:30:00+00:00",
            "valid_to": "2026-11-22T14:00:00+00:00",
            "flow_estimated_soc_percent": 57.8,
            "flow_battery_charge_kwh": 0.0,
            "flow_battery_to_home_kwh": 0.676,
            "flow_battery_export_kwh": 0.0,
        },
        {
            "valid_from": "2026-11-22T16:00:00+00:00",
            "valid_to": "2026-11-22T16:30:00+00:00",
            "flow_estimated_soc_percent": 38.7,
            "flow_battery_charge_kwh": 0.0,
            "flow_battery_to_home_kwh": 1.531,
            "flow_battery_export_kwh": 1.862,
        },
    ]
    state = {
        "rolling_export_plan": _plan(),
        "current_routing_snapshot": {
            "available": True,
            "generated_at": NOW.isoformat(),
            "routing_valid_from": "2026-11-22T13:30:00+00:00",
            "routing_valid_to": "2026-11-22T14:00:00+00:00",
            "simulated_soc_percent": 59.2,
        },
        "today_slots": today,
    }
    rebase(
        state,
        now=NOW,
        config=SimpleNamespace(
            battery_capacity_kwh=CAPACITY, discharge_efficiency=0.95
        ),
    )
    assert state["flow_soc_continuity"]["physical_same_scan_proven"] is True
    assert state["flow_soc_continuity"]["independent_digital_twin_soc_percent"] == 59.2
    assert 80.0 < today[0]["flow_estimated_soc_percent"] < 87.3
    assert 70.0 < today[1]["flow_estimated_soc_percent"] < 87.3
    assert "verified physical lower bound" in today[1]["flow_soc_basis"]


def test_card_never_hides_export_behind_house_only_description():
    text = DASHBOARD.read_text(encoding="utf-8")
    assert "{% set export_flow = p.get('flow_battery_export_kwh') %}" in text
    assert "Battery powers house + planned grid export" in text
    assert "export_flow | float > 0.001" in text
    assert "physical_soc_from_flow" in text
    for path in (FLOW, CONTINUITY, DASHBOARD):
        source = path.read_text(encoding="utf-8")
        assert "services.async_call" not in source
        assert "select.select_option" not in source
        assert "number.set_value" not in source
