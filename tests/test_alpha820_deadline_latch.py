"""Alpha8.20 regressions for the hard 10%-deadline latch."""

from __future__ import annotations

import ast
import math
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
LATCH = KEMS / "agile_deadline_latch.py"
COMPAT = KEMS / "agile_alpha7_compat.py"


def _load_latch_functions() -> dict[str, Any]:
    tree = ast.parse(LATCH.read_text(encoding="utf-8"), filename=str(LATCH))
    wanted = {
        "_number",
        "_datetime",
        "_guard",
        "_soc_and_target",
        "_deadline_from",
        "_release_reason",
        "_suppressed_active_guard",
        "_new_latch",
        "_safe_deadline_power",
        "_apply_latch",
        "_dispatch_with_deadline_latch",
    }
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            body.append(node)

    namespace: dict[str, Any] = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "math": math,
        "SimulationConfig": Any,
        "_EPSILON": 1e-6,
        "_SOC_TOLERANCE_PERCENT": 0.05,
        "_LATCH_ATTR": "_kems_deadline_discharge_latch",
        "_DEADLINE_MODES": frozenset({"deadline_following", "maximum_discharge"}),
        "_PRICE_MODES": frozenset({"price_optimised", "deadline_following"}),
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
            str(LATCH),
            "exec",
        ),
        namespace,
    )
    return namespace


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
    )


def _suppressed_targets(*, soc: float = 82.1) -> dict[str, Any]:
    return {
        "mode": "price_optimised",
        "action": "hold battery — future price-selected plan physically covers target",
        "house_battery_kw": 1.5,
        "planned_price_export_kw": 0.0,
        "battery_export_target_kw": 0.0,
        "battery_discharge_target_kw": 1.5,
        "deadline_guard_suppressed_by_plan_coverage": True,
        "deadline_guard": {
            "raw_mode": "deadline_following",
            "mode": "price_optimised",
            "deadline_guard_active": False,
            "suppressed_by_economic_plan_coverage": True,
            "deadline": "2026-08-25T22:30:00+00:00",
            "target_soc_percent": 10.0,
            "simulated_soc_percent": soc,
            "current_battery_headroom_kw": 7.0,
        },
        "solar_aware_inverter_headroom": {
            "battery_inverter_headroom_kw": 7.0,
            "deadline_guard_applied": False,
            "economic_plan_coverage_override": True,
        },
    }


def test_deadline_latch_is_installed_after_dispatch_reconciliation() -> None:
    compat = COMPAT.read_text(encoding="utf-8")
    dispatch = '("agile_dispatch_reconciliation", "install_dispatch_reconciliation")'
    latch = '("agile_deadline_latch", "install_deadline_latch")'
    final = '("agile_runtime_reconciliation", "install_runtime_reconciliation")'
    assert dispatch in compat
    assert latch in compat
    assert final in compat
    assert compat.index(dispatch) < compat.index(latch) < compat.index(final)


def test_suppressed_deadline_guard_is_recognised_as_latch_trigger() -> None:
    ns = _load_latch_functions()
    targets = _suppressed_targets()
    guard = targets["deadline_guard"]
    assert ns["_suppressed_active_guard"](targets, guard) is True


def test_latch_does_not_release_merely_because_recalculated_slack_returns() -> None:
    ns = _load_latch_functions()
    latch = {
        "active": True,
        "activated_at": "2026-08-25T16:00:00+00:00",
        "deadline": "2026-08-25T22:30:00+00:00",
        "target_soc_percent": 10.0,
    }
    guard = {
        "mode": "price_optimised",
        "target_soc_percent": 10.0,
        "simulated_soc_percent": 63.8,
        "deadline": "2026-08-25T22:30:00+00:00",
    }
    assert (
        ns["_release_reason"](
            latch,
            guard,
            now=datetime(2026, 8, 25, 18, 0, tzinfo=UTC),
        )
        is None
    )


def test_rolling_replan_cannot_switch_latched_deadline_back_to_price_optimised() -> (
    None
):
    ns = _load_latch_functions()
    manager = SimpleNamespace()
    plan: dict[str, Any] = {
        "exportable_battery_energy_kwh": 40.0,
        "selected_slots": [],
    }
    state: dict[str, Any] = {"today_slots": []}
    responses = [
        _suppressed_targets(soc=82.1),
        {
            **_suppressed_targets(soc=70.4),
            "deadline_guard_suppressed_by_plan_coverage": False,
            "deadline_guard": {
                "mode": "price_optimised",
                "deadline_guard_active": False,
                "deadline": "2026-08-25T22:30:00+00:00",
                "target_soc_percent": 10.0,
                "simulated_soc_percent": 70.4,
                "current_battery_headroom_kw": 7.0,
            },
        },
    ]

    def original(self, state, plan, *, now, config, tariff):
        return responses.pop(0)

    ns["_original_deadline_latch_dispatch"] = original
    ns["reconciliation"] = SimpleNamespace(
        _rebalance_deadline_forced_current_slot=lambda *args, **kwargs: {
            "applied": False,
            "reason": "fixture has no later selected slot",
        }
    )

    first = ns["_dispatch_with_deadline_latch"](
        manager,
        state,
        plan,
        now=datetime(2026, 8, 25, 16, 30, tzinfo=UTC),
        config=_config(),
        tariff=object(),
    )
    second = ns["_dispatch_with_deadline_latch"](
        manager,
        state,
        plan,
        now=datetime(2026, 8, 25, 17, 0, tzinfo=UTC),
        config=_config(),
        tariff=object(),
    )

    assert first["mode"] == "deadline_following"
    assert first["deadline_latch_active"] is True
    assert first["battery_discharge_target_kw"] == 7.0
    assert first["battery_export_target_kw"] == 5.5
    assert second["mode"] == "deadline_following"
    assert second["deadline_latch_active"] is True
    assert second["battery_discharge_target_kw"] == 7.0
    assert "_kems_deadline_discharge_latch" in manager.__dict__


def test_latch_releases_only_at_target_or_original_cheap_deadline() -> None:
    ns = _load_latch_functions()
    latch = {
        "active": True,
        "activated_at": "2026-08-25T16:00:00+00:00",
        "deadline": "2026-08-25T22:30:00+00:00",
        "target_soc_percent": 10.0,
    }
    target_guard = {
        "target_soc_percent": 10.0,
        "simulated_soc_percent": 10.0,
        "deadline": "2026-08-25T22:30:00+00:00",
    }
    assert (
        ns["_release_reason"](
            latch,
            target_guard,
            now=datetime(2026, 8, 25, 21, 0, tzinfo=UTC),
        )
        == "target_reached"
    )

    above_target = {
        "target_soc_percent": 10.0,
        "simulated_soc_percent": 13.4,
        "deadline": "2026-08-26T22:30:00+00:00",
    }
    assert (
        ns["_release_reason"](
            latch,
            above_target,
            now=datetime(2026, 8, 25, 22, 30, tzinfo=UTC),
        )
        == "cheap_window_started"
    )


def test_deadline_latch_remains_shadow_only() -> None:
    source = LATCH.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "commands_permitted = True" not in source
    assert "real hardware writes stay blocked" in source
