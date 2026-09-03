"""Alpha8.76 regressions for the 15/10/12 battery safety hierarchy."""

from __future__ import annotations

import ast
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
SOURCE = KEMS / "agile_safety_floor.py"
RUNTIME = KEMS / "agile_smart_export_runtime.py"
SETTINGS = KEMS / "settings.py"


@dataclass(frozen=True)
class _Config:
    battery_reserve_percent: float


def _helpers() -> dict[str, Any]:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    wanted = {
        "_number",
        "_planning_config",
        "_hard_safety_floor_latched",
        "_apply_hard_safety_floor",
    }
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    namespace: dict[str, Any] = {
        "Any": Any,
        "SimulationConfig": _Config,
        "math": math,
        "replace": replace,
        "PLANNING_TARGET_SOC_PERCENT": 15.0,
        "HARD_SAFETY_FLOOR_SOC_PERCENT": 10.0,
        "HARD_SAFETY_RECOVERY_SOC_PERCENT": 12.0,
        "_EPSILON": 1e-6,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, SOURCE.as_posix(), "exec"), namespace)
    return namespace


def test_planning_target_is_at_least_fifteen_percent() -> None:
    planning_config = _helpers()["_planning_config"]

    assert planning_config(_Config(10.0)).battery_reserve_percent == 15.0
    assert planning_config(_Config(15.0)).battery_reserve_percent == 15.0
    assert planning_config(_Config(20.0)).battery_reserve_percent == 20.0


def test_hard_floor_activates_at_ten_and_releases_only_at_twelve() -> None:
    latch = _helpers()["_hard_safety_floor_latched"]
    owner = SimpleNamespace()

    assert latch(owner, 10.1) is False
    assert latch(owner, 10.0) is True
    assert latch(owner, 10.1) is True
    assert latch(owner, 11.9) is True
    assert latch(owner, 12.0) is False
    assert latch(owner, 11.5) is False


def test_unknown_soc_cannot_silently_release_an_active_safety_latch() -> None:
    latch = _helpers()["_hard_safety_floor_latched"]
    owner = SimpleNamespace(_kems_hard_safety_floor_latched=True)

    assert latch(owner, None) is True
    assert owner._kems_hard_safety_floor_latched is True


def test_active_floor_stops_house_export_and_future_export_plan() -> None:
    apply_floor = _helpers()["_apply_hard_safety_floor"]
    plan = {
        "available": True,
        "dispatch_mode": "price_optimised",
        "target_soc_percent": 15.0,
        "current_house_battery_kw": 1.336,
        "current_battery_export_target_kw": 2.0,
        "current_battery_discharge_target_kw": 3.336,
        "planned_battery_export_kwh": 4.0,
        "selected_slots": [{"valid_from": "future"}],
        "next_export_slot": {"valid_from": "future"},
    }

    result = apply_floor(plan, soc=9.958, latched=True)

    assert result["dispatch_mode"] == "hard_safety_floor"
    assert result["hard_safety_superseded_dispatch_mode"] == "price_optimised"
    assert result["current_house_battery_kw"] == 0.0
    assert result["current_battery_export_target_kw"] == 0.0
    assert result["current_battery_discharge_target_kw"] == 0.0
    assert result["planned_battery_export_kwh"] == 0.0
    assert result["selected_slots"] == []
    assert result["next_export_slot"] is None
    assert result["hard_safety_floor_active"] is True
    assert result["hard_reserve_floor_active"] is True


def test_active_floor_overrides_power_down_battery_discharge() -> None:
    apply_floor = _helpers()["_apply_hard_safety_floor"]
    plan = {
        "available": True,
        "dispatch_mode": "power_down_session",
        "current_house_battery_kw": 1.0,
        "current_battery_export_target_kw": 6.0,
        "current_battery_discharge_target_kw": 7.0,
        "planned_battery_export_kwh": 3.5,
    }

    result = apply_floor(plan, soc=10.0, latched=True)

    assert result["dispatch_mode"] == "hard_safety_floor"
    assert result["hard_safety_superseded_dispatch_mode"] == "power_down_session"
    assert result["current_house_battery_kw"] == 0.0
    assert result["current_battery_export_target_kw"] == 0.0
    assert result["current_battery_discharge_target_kw"] == 0.0


def test_cheap_charge_keeps_ownership_so_latched_battery_can_recover() -> None:
    apply_floor = _helpers()["_apply_hard_safety_floor"]
    plan = {
        "available": True,
        "dispatch_mode": "cheap_charge",
        "current_house_battery_kw": 0.0,
        "current_battery_export_target_kw": 0.0,
        "current_battery_discharge_target_kw": 0.0,
        "charge_target_kw": 7.0,
    }

    result = apply_floor(plan, soc=9.5, latched=True)

    assert result["dispatch_mode"] == "cheap_charge"
    assert result["charge_target_kw"] == 7.0
    assert result["hard_safety_floor_active"] is True
    assert result["hard_safety_charge_recovery_active"] is True


def test_recovery_resumes_house_bridge_below_planning_target() -> None:
    apply_floor = _helpers()["_apply_hard_safety_floor"]
    plan = {
        "available": True,
        "dispatch_mode": "price_optimised",
        "target_soc_percent": 15.0,
        "current_house_battery_kw": 1.25,
        "current_battery_export_target_kw": 0.0,
        "current_battery_discharge_target_kw": 1.25,
    }

    result = apply_floor(plan, soc=12.0, latched=False)

    assert result["current_house_battery_kw"] == 1.25
    assert result["current_battery_export_target_kw"] == 0.0
    assert result["current_battery_discharge_target_kw"] == 1.25
    assert result["planning_target_soc_percent"] == 15.0
    assert result["planning_target_reached"] is True
    assert result["hard_safety_floor_active"] is False


def test_alpha876_scope_install_order_and_release_metadata() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    runtime = RUNTIME.read_text(encoding="utf-8")
    settings = SETTINGS.read_text(encoding="utf-8")
    source = SOURCE.read_text(encoding="utf-8")

    assert manifest["version"] == "0.8.0-alpha8.76"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    reason = bundle["maintenance"]["reason"].lower()
    assert "15%" in reason
    assert "10%" in reason
    assert "12%" in reason
    assert runtime.index("install_intelligent_dispatch_replan()") < runtime.index(
        "install_agile_safety_floor()"
    )
    assert "float(values[CONF_BATTERY_RESERVE]),\n                    15.0" in settings
    assert "HARD_SAFETY_FLOOR_SOC_PERCENT = 10.0" in source
    assert "HARD_SAFETY_RECOVERY_SOC_PERCENT = 12.0" in source
    assert '"hardware_writes": "blocked"' in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
