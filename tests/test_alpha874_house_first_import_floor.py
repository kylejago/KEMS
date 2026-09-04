"""Alpha8.74 regression for the live non-cheap house-first import floor."""

from __future__ import annotations

import ast
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).parents[1]
RUNTIME = ROOT / "custom_components" / "kems" / "agile_total_discharge_ledger.py"


def _target_function():
    tree = ast.parse(RUNTIME.read_text())
    wanted = {"_number", "_dt", "_current_total_discharge_targets"}
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
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, RUNTIME.as_posix(), "exec"), namespace)
    return namespace["_current_total_discharge_targets"]


def _allocation(*, planned_kwh: float) -> SimpleNamespace:
    return SimpleNamespace(
        valid_from=datetime(2026, 9, 3, 18, 0, tzinfo=UTC),
        valid_to=datetime(2026, 9, 3, 18, 30, tzinfo=UTC),
        planned_total_discharge_kwh=planned_kwh,
    )


def _segments(*, battery_kw: float = 7.0, solar_kw: float = 0.035):
    return [
        {
            "start": datetime(2026, 9, 3, 18, 20, tzinfo=UTC),
            "end": datetime(2026, 9, 3, 18, 25, tzinfo=UTC),
            "battery_kw": battery_kw,
            "solar_kw": solar_kw,
        }
    ]


def test_uploaded_1920_case_covers_live_net_house_instead_of_importing() -> None:
    """Lock the exact Alpha8.73 19:20 pacing failure from the field diagnostic."""
    target = _target_function()
    now = datetime(2026, 9, 3, 18, 20, 46, 349216, tzinfo=UTC)
    remaining_hours = (
        datetime(2026, 9, 3, 18, 30, tzinfo=UTC) - now
    ).total_seconds() / 3600.0
    old_paced_kw = 0.139 / remaining_hours

    house_kw, export_kw, total_kw = target(
        allocations=[_allocation(planned_kwh=0.139)],
        capacity_segments=_segments(),
        now=now,
        house_kw=1.313,
        export_limit_kw=7.0,
        house_floor_available=True,
    )

    assert old_paced_kw == pytest.approx(0.904, abs=0.002)
    assert house_kw == pytest.approx(1.278)
    assert export_kw == 0.0
    assert total_kw == pytest.approx(1.278)
    assert max(1.313 - 0.035 - house_kw, 0.0) == 0.0


def test_house_floor_applies_even_when_price_ledger_did_not_select_current_slot() -> (
    None
):
    """A price hold may suppress export, never ordinary non-cheap home service."""
    target = _target_function()
    now = datetime(2026, 9, 3, 18, 20, 46, 349216, tzinfo=UTC)

    assert target(
        allocations=[],
        capacity_segments=_segments(),
        now=now,
        house_kw=1.313,
        export_limit_kw=7.0,
        house_floor_available=True,
    ) == pytest.approx((1.278, 0.0, 1.278))


def test_zero_available_discharge_keeps_reserve_floor_authoritative() -> None:
    """At the protected target, no unallocated house discharge is invented."""
    target = _target_function()
    now = datetime(2026, 9, 3, 18, 20, 46, 349216, tzinfo=UTC)

    assert (
        target(
            allocations=[],
            capacity_segments=_segments(),
            now=now,
            house_kw=1.313,
            export_limit_kw=7.0,
            house_floor_available=False,
        )
        is None
    )


def test_physical_battery_headroom_still_caps_house_floor() -> None:
    target = _target_function()
    now = datetime(2026, 9, 3, 18, 20, 46, 349216, tzinfo=UTC)

    assert target(
        allocations=[],
        capacity_segments=_segments(battery_kw=0.5, solar_kw=0.035),
        now=now,
        house_kw=1.313,
        export_limit_kw=7.0,
        house_floor_available=True,
    ) == pytest.approx((0.5, 0.0, 0.5))


def test_discretionary_export_remains_price_paced_after_house_is_served() -> None:
    target = _target_function()
    now = datetime(2026, 9, 3, 18, 15, tzinfo=UTC)

    assert target(
        allocations=[_allocation(planned_kwh=0.5)],
        capacity_segments=[
            {
                "start": now,
                "end": now + timedelta(minutes=5),
                "battery_kw": 7.0,
                "solar_kw": 0.0,
            }
        ],
        now=now,
        house_kw=1.0,
        export_limit_kw=7.0,
        house_floor_available=True,
    ) == pytest.approx((1.0, 1.0, 2.0))


def test_higher_priority_modes_and_hardware_boundary_are_unchanged() -> None:
    runtime = RUNTIME.read_text()

    assert (
        'mode in {"cheap_charge", "happy_hour_charge", "power_down_session"}' in runtime
    )
    assert 'mode not in {"deadline_following", "maximum_discharge"}' in runtime
    assert "house_floor_available=normal_required > _EPSILON" in runtime
    assert '"hardware_writes": "blocked"' in runtime


def test_alpha874_version_and_release_scope() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())
    version = manifest["version"]

    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    release_number = int(version.rsplit(".", 1)[1])
    assert release_number >= 74
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.0"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    if release_number == 74:
        assert "house" in bundle["maintenance"]["reason"].lower()
        assert "day-rate" in bundle["maintenance"]["reason"].lower()
