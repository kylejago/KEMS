"""Alpha8.75 regressions for house-first routing after the optimiser target."""

from __future__ import annotations

import ast
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
SOURCE = KEMS / "agile_solar_net_demand.py"


@dataclass(frozen=True)
class _Allocation:
    valid_from: datetime
    valid_to: datetime
    allocated_kwh: float


def _helpers() -> dict[str, Any]:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
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
    exec(compile(module, SOURCE.as_posix(), "exec"), namespace)
    return namespace


def _segment(
    start: datetime,
    *,
    solar_kw: float = 0.0,
    battery_kw: float = 7.0,
) -> dict[str, Any]:
    return {
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=5)).isoformat(),
        "solar_kw": solar_kw,
        "battery_kw": battery_kw,
    }


def test_sep3_2158_live_target_reached_case_keeps_house_off_day_rate_grid() -> None:
    """Reproduce the Alpha8.74 21:58 BST import transition at 9.958% SOC."""
    target = _helpers()["_current_physical_targets"]
    now = datetime(2026, 9, 3, 20, 58, tzinfo=UTC)
    allocation = _Allocation(
        now - timedelta(minutes=28), now + timedelta(minutes=2), 1.0
    )

    house, export, total = target(
        allocations=(allocation,),
        capacity_segments=[_segment(now)],
        now=now,
        house_kw=1.336,
        export_limit_kw=7.0,
        current_soc_percent=9.958,
        target_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )

    assert house == 1.336
    assert export == 0.0
    assert total == 1.336
    assert round(1.336 - house, 3) == 0.0


def test_target_reached_with_live_solar_serves_only_net_house_from_battery() -> None:
    target = _helpers()["_current_physical_targets"]
    now = datetime(2026, 9, 3, 20, 58, tzinfo=UTC)

    house, export, total = target(
        allocations=(),
        capacity_segments=[_segment(now, solar_kw=0.035)],
        now=now,
        house_kw=1.313,
        export_limit_kw=7.0,
        current_soc_percent=10.0,
        target_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )

    assert house == 1.278
    assert export == 0.0
    assert total == 1.278


def test_below_target_never_restarts_deliberate_export() -> None:
    target = _helpers()["_current_physical_targets"]
    now = datetime(2026, 9, 3, 21, 0, tzinfo=UTC)
    allocation = _Allocation(now, now + timedelta(minutes=30), 3.5)

    house, export, total = target(
        allocations=(allocation,),
        capacity_segments=[_segment(now)],
        now=now,
        house_kw=0.75,
        export_limit_kw=7.0,
        current_soc_percent=8.5,
        target_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )

    assert house == 0.75
    assert export == 0.0
    assert total == 0.75


def test_house_bridge_remains_bounded_by_real_battery_power() -> None:
    target = _helpers()["_current_physical_targets"]
    now = datetime(2026, 9, 3, 21, 0, tzinfo=UTC)

    house, export, total = target(
        allocations=(),
        capacity_segments=[_segment(now, battery_kw=0.8)],
        now=now,
        house_kw=1.3,
        export_limit_kw=7.0,
        current_soc_percent=9.5,
        target_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )

    assert house == 0.8
    assert export == 0.0
    assert total == 0.8


def test_target_guard_still_allows_only_surplus_export_above_house() -> None:
    target = _helpers()["_current_physical_targets"]
    now = datetime(2026, 9, 3, 21, 0, tzinfo=UTC)
    allocation = _Allocation(now, now + timedelta(minutes=30), 1.0)

    house, export, total = target(
        allocations=(allocation,),
        capacity_segments=[_segment(now)],
        now=now,
        house_kw=0.5,
        export_limit_kw=7.0,
        current_soc_percent=10.2,
        target_soc_percent=10.0,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )

    assert house == 0.5
    assert export == 0.786
    assert total == 1.286


def test_alpha875_scope_priority_and_hardware_isolation() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    source = SOURCE.read_text(encoding="utf-8")
    version = manifest["version"]

    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    release_number = int(version.rsplit(".", 1)[1])
    assert str(version).startswith("0.9.0-alpha9") or release_number >= 75
    assert bundle["maintenance"]["affected_components"] in (
        ["kems_core", "dashboard"],
        ["kems_core", "dashboard", "panel", "property_web", "pi_agent", "public_web"],
    )
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert str(bundle["components"]["property_web"]["version"]).startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-web.")
    )
    assert str(bundle["components"]["pi_agent"]["version"]).startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-web.")
    )
    assert str(bundle["components"]["public_web"]["version"]).startswith(
        ("0.8.0-alpha8-web.", "0.9.0-alpha9-public.")
    )
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    if release_number == 75:
        assert "planning target" in bundle["maintenance"]["reason"].lower()
        assert "avoidable day-rate" in bundle["maintenance"]["reason"].lower()
    assert (
        'if mode in {"cheap_charge", "happy_hour_charge", "power_down_session"}'
        in source
    )
    assert 'if mode not in {"deadline_following", "maximum_discharge"}' in source
    assert '"planning_target_house_bridge_active": target_reached' in source
    assert '"hard_reserve_floor_active": False' in source
    assert '"hardware_writes": "blocked"' in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
