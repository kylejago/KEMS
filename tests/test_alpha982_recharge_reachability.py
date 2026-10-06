"""Alpha9.82 recharge-reachability planning regressions."""

from __future__ import annotations

import ast
from datetime import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
MODULE = KEMS / "agile_recharge_reachability.py"
RUNTIME = KEMS / "agile_smart_export_runtime.py"


def _helpers():
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {
        "_number",
        "_cheap_window_hours",
        "_required_precheap_soc_percent",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace = {
        "Any": object,
        "datetime": __import__("datetime").datetime,
        "time": time,
        "timedelta": __import__("datetime").timedelta,
        "math": __import__("math"),
        "SimulationConfig": object,
        "TariffSettings": object,
        "FULL_CHARGE_TARGET_PERCENT": 100.0,
        "_EPSILON": 1e-6,
    }
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, MODULE.as_posix(), "exec"), namespace)
    return namespace


def _config(*, max_charge_kw: float = 7.0):
    return SimpleNamespace(
        battery_capacity_kwh=56.42,
        max_charge_kw=max_charge_kw,
        charge_efficiency=0.95,
    )


def _tariff():
    return SimpleNamespace(
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
    )


def test_current_hardware_requires_about_29_percent_at_cheap_start() -> None:
    helpers = _helpers()
    evidence = helpers["_required_precheap_soc_percent"](_config(), _tariff())

    assert evidence["guaranteed_cheap_window_hours"] == 6.0
    assert evidence["maximum_stored_charge_kwh"] == pytest.approx(39.9)
    assert evidence["maximum_soc_gain_percent"] == pytest.approx(70.72, abs=0.001)
    assert evidence["required_precheap_soc_percent"] == pytest.approx(
        29.28,
        abs=0.001,
    )


def test_faster_charger_can_remove_the_recharge_floor() -> None:
    helpers = _helpers()
    evidence = helpers["_required_precheap_soc_percent"](
        _config(max_charge_kw=10.0),
        _tariff(),
    )

    assert evidence["required_precheap_soc_percent"] == 0.0


def test_recharge_floor_is_planning_only() -> None:
    source = MODULE.read_text(encoding="utf-8")
    assert '"hardware_writes": "blocked"' in source
    assert "async_call(" not in source
    assert "services.async_call" not in source
    assert "foxess" not in source.lower()


def test_runtime_installs_recharge_floor_after_safety_floor() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    safety_index = source.index("install_agile_safety_floor()")
    recharge_index = source.index("install_recharge_reachability()")
    assert recharge_index > safety_index
    assert recharge_index < source.index("install_observability_clarity()")
