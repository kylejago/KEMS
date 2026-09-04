"""Regression coverage for deadline-arrival reserve ownership.

Alpha8.75 supersedes the Alpha8.45 assumption that the 10% optimiser target is
an absolute house-discharge floor. The target still constrains deliberate
export, while house-first battery supply continues outside confirmed cheap time.
"""

from __future__ import annotations

import ast
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from kems_core.tomorrow_soc_handoff import (
    project_tomorrow_midnight_soc,
    reconcile_precheap_projection,
)

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
ROUTING = INTEGRATION / "agile_solar_net_demand.py"
ROLLING = INTEGRATION / "agile_rolling_replan_runtime.py"
SETTLEMENT = INTEGRATION / "agile_current_day_settlement.py"
SETTLED_HANDOFF = INTEGRATION / "agile_settled_soc_handoff.py"


@dataclass(frozen=True)
class _Allocation:
    valid_from: datetime
    valid_to: datetime
    allocated_kwh: float


def _routing_target():
    tree = ast.parse(ROUTING.read_text())
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
        "HARD_FLOOR_GUARD_MINUTES": 5.0,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, ROUTING.as_posix(), "exec"), namespace)
    return namespace["_current_physical_targets"]


def _segment(start: datetime, *, solar_kw: float = 0.0) -> dict[str, Any]:
    return {
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=5)).isoformat(),
        "solar_kw": solar_kw,
        "battery_kw": 7.0,
    }


def test_ten_percent_planning_target_stops_export_but_keeps_house_bridge() -> None:
    target = _routing_target()
    start = datetime(2026, 8, 28, 21, 30, tzinfo=UTC)
    allocation = _Allocation(start, start + timedelta(minutes=30), 1.0)

    house, export, total = target(
        allocations=(allocation,),
        capacity_segments=[_segment(start)],
        now=start,
        house_kw=2.0,
        export_limit_kw=7.0,
        current_soc_percent=10.0,
        target_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )

    assert house == 2.0
    assert export == 0.0
    assert total == 2.0


def test_five_minute_guard_tapers_only_discretionary_export_near_target() -> None:
    target = _routing_target()
    start = datetime(2026, 8, 28, 21, 30, tzinfo=UTC)
    allocation = _Allocation(start, start + timedelta(minutes=30), 1.0)

    house, export, total = target(
        allocations=(allocation,),
        capacity_segments=[_segment(start)],
        now=start,
        house_kw=0.5,
        export_limit_kw=7.0,
        current_soc_percent=10.2,
        target_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )

    usable_ac_kwh = 0.2 / 100.0 * 56.42 * 0.95
    expected_limit_kw = usable_ac_kwh / (5.0 / 60.0)
    assert house == 0.5
    assert export == round(expected_limit_kw - house, 3) == 0.786
    assert total == round(expected_limit_kw, 3) == 1.286
    assert export > 0.0


def test_house_first_routing_is_unchanged_when_safely_above_floor() -> None:
    target = _routing_target()
    start = datetime(2026, 8, 28, 21, 0, tzinfo=UTC)
    allocation = _Allocation(start, start + timedelta(minutes=30), 0.0)

    house, export, total = target(
        allocations=(allocation,),
        capacity_segments=[_segment(start, solar_kw=0.5)],
        now=start,
        house_kw=2.0,
        export_limit_kw=7.0,
        current_soc_percent=15.0,
        target_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )

    assert house == 1.5
    assert export == 0.0
    assert total == 1.5


def _rolling_soc_helpers():
    tree = ast.parse(ROLLING.read_text())
    wanted = {"_number", "_current_agile_soc", "_current_agile_soc_source"}
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace: dict[str, Any] = {"Any": Any, "math": math}
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, ROLLING.as_posix(), "exec"), namespace)
    return namespace["_current_agile_soc"], namespace["_current_agile_soc_source"]


def test_settled_current_soc_wins_over_stale_replay_and_routing_soc() -> None:
    current_soc, source = _rolling_soc_helpers()
    state = {
        "current_day_settlement_reconciliation": {
            "applied": True,
            "ending_soc_percent": 8.46,
        },
        "current_routing_snapshot": {
            "available": True,
            "simulated_soc_percent": 24.3,
        },
        "periods": {
            "today": {
                "agile_smart_export": {
                    "ending_soc_percent": 24.3,
                }
            }
        },
    }

    assert current_soc(state) == 8.46
    assert source(state) == "settled current-day digital-twin SOC"


def _rolling_plan_function():
    tree = ast.parse(ROLLING.read_text())
    wanted = {
        "_number",
        "_datetime",
        "_current_agile_soc",
        "_current_agile_soc_source",
        "_predicted_house_until_deadline",
        "_current_house_headroom_kw",
        "_rolling_plan",
    }
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]

    class _Agile:
        @staticmethod
        def _next_cheap(now, tariff):
            del now, tariff
            return datetime(2026, 8, 28, 22, 30, tzinfo=UTC)

    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "math": math,
        "_EPSILON": 1e-6,
        "SAFETY_HEADROOM_MINUTES": 30,
        "agile": _Agile,
        "SimulationConfig": object,
        "TariffSettings": object,
        "_effective_deadline_kw": lambda config: 7.0,
        "_target_percent": lambda config: 10.0,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, ROLLING.as_posix(), "exec"), namespace)
    return namespace["_rolling_plan"]


def test_rolling_reserve_declines_to_ten_percent_after_protecting_house() -> None:
    rolling_plan = _rolling_plan_function()
    manager = SimpleNamespace(
        _rolling_predicted_house_kwh=1.446,
        _panel_today_records=[],
    )
    config = SimpleNamespace(
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
        max_discharge_kw=7.0,
    )
    state = {
        "current_day_settlement_reconciliation": {
            "applied": True,
            "ending_soc_percent": 20.0,
        },
        "today_slots": [
            {
                "valid_from": "2026-08-28T21:30:00+00:00",
                "valid_to": "2026-08-28T22:00:00+00:00",
                "rate_pence": 12.7,
            },
            {
                "valid_from": "2026-08-28T22:00:00+00:00",
                "valid_to": "2026-08-28T22:30:00+00:00",
                "rate_pence": 11.99,
            },
        ],
    }

    plan = rolling_plan(
        manager,
        state,
        now=datetime(2026, 8, 28, 21, 38, tzinfo=UTC),
        config=config,
        tariff=object(),
    )

    expected_reserve = 10.0 + (1.446 / 0.95 / 56.42 * 100.0)
    assert plan["available"] is True
    assert plan["simulated_soc_source"] == "settled current-day digital-twin SOC"
    assert plan["target_soc_percent"] == 10.0
    assert plan["arrival_reserve_soc_percent"] == round(expected_reserve, 2) == 12.7
    assert plan["arrival_reserve_margin_percent"] == 2.7
    assert "declines toward target" in plan["arrival_reserve_policy"]


def test_below_reserve_handoff_never_invents_an_upward_soc_jump() -> None:
    projected, evidence = reconcile_precheap_projection(
        projected_precheap_soc_percent=10.0,
        current_soc_percent=8.5,
        remaining_discharge_capacity_kwh=6.007,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
        reserve_soc_percent=10.0,
        target_physically_reachable_now=False,
    )

    assert projected == 8.5
    assert evidence["current_soc_percent"] == 8.5
    assert evidence["reserve_soc_percent"] == 10.0
    assert "below reserve" in evidence["reason"]

    midnight, handoff = project_tomorrow_midnight_soc(
        now=datetime(2026, 8, 28, 21, 38, tzinfo=UTC),
        current_soc_percent=8.5,
        projected_precheap_soc_percent=projected,
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
    )
    assert handoff["starting_soc_percent"] == 8.5
    assert midnight == 14.393


def test_settlement_rebuilds_tomorrow_after_corrected_soc_is_published() -> None:
    source = SETTLEMENT.read_text()
    helper = SETTLED_HANDOFF.read_text()
    publish_at = source.index("self._publish(self._state)")
    refresh_at = source.index("refresh_tomorrow_handoff_from_settled_soc(", publish_at)

    assert publish_at < refresh_at
    assert 'state["settled_soc_handoff_reconciliation"]' in helper
    assert '"soc_authority"' in helper
    assert "manager._compare_day(" in helper
    assert "manager._publish(manager._state)" in helper
    assert '"hardware_writes": "blocked"' in helper
    assert ".services.async_call(" not in helper
    assert "providers.foxess" not in helper


def test_alpha845_release_contract() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())
    version = manifest["version"]

    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert int(version.rsplit(".", 1)[1]) >= 45
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
