"""Regression tests for post-Alpha8 Full KEMS Agile forecast arbitrage."""

from __future__ import annotations

import ast
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
MODULE = KEMS / "agile_forecast_arbitrage.py"
COMPAT = KEMS / "agile_alpha7_compat.py"
MANIFEST = KEMS / "manifest.json"


def _load_helpers():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    function_names = {
        "_number",
        "_dt",
        "_effective_precheap_target",
        "_economic_export_floor_pence",
        "_forecast_confidence",
        "_conservative_house_kw",
        "_forecast_spill_projection",
        "_slot_map",
        "_selected_allocations",
        "_apply_floor_and_forecast_target",
        "_spill_reference_rate",
        "_retime_for_solar_headroom",
    }
    constant_names = {
        "MIN_HEADROOM_FORECAST_CONFIDENCE_PERCENT",
        "HEADROOM_MIN_PRICE_ADVANTAGE_PENCE",
        "_EPSILON",
    }
    body: list[ast.stmt] = []
    for node in tree.body:
        future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
        constant = isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in constant_names
            for target in node.targets
        )
        helper = isinstance(node, ast.FunctionDef) and node.name in function_names
        if future or constant or helper:
            body.append(node)

    namespace = {
        "Any": Any,
        "UTC": UTC,
        "datetime": datetime,
        "timedelta": timedelta,
        "math": math,
        "_target_percent": lambda config: 10.0,
    }
    isolated = ast.Module(body=body, type_ignores=[])
    exec(
        compile(ast.fix_missing_locations(isolated), str(MODULE), "exec"),
        namespace,
    )
    return namespace


def _slot(start: datetime, rate: float, allocation: float = 0.0) -> dict[str, Any]:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "label": start.strftime("%H:%M"),
        "rate_pence": rate,
        "rolling_planned_battery_export_kwh": allocation,
    }


def test_forecast_minimum_precheap_soc_becomes_live_floor() -> None:
    helpers = _load_helpers()
    config = SimpleNamespace(battery_reserve_percent=10.0)
    forecast_plan = SimpleNamespace(
        ready=True,
        minimum_precheap_soc_percent=19.3,
    )

    normal, effective = helpers["_effective_precheap_target"](config, forecast_plan)

    assert normal == 10.0
    assert effective == 19.3


def test_overnight_rate_is_the_ordinary_export_economic_floor() -> None:
    helpers = _load_helpers()
    tariff = SimpleNamespace(offpeak_rate_pence=3.5)

    assert helpers["_economic_export_floor_pence"](tariff) == 3.5


def test_plan_blocks_sub_replacement_export_and_protects_forecast_soc() -> None:
    helpers = _load_helpers()
    start = datetime(2026, 8, 22, 5, 30, tzinfo=UTC)
    low = _slot(start, 3.4)
    high = _slot(start + timedelta(minutes=30), 12.94)
    state = {"today_slots": [low, high]}
    plan = {
        "target_soc_percent": 10.0,
        "exportable_battery_energy_kwh": 4.0,
        "selected_slots": [
            {
                "valid_from": low["valid_from"],
                "planned_battery_export_kwh": 1.0,
            },
            {
                "valid_from": high["valid_from"],
                "planned_battery_export_kwh": 3.0,
            },
        ],
    }
    config = SimpleNamespace(
        battery_reserve_percent=10.0,
        battery_capacity_kwh=10.0,
        discharge_efficiency=0.95,
    )
    tariff = SimpleNamespace(offpeak_rate_pence=3.5)
    forecast_plan = SimpleNamespace(
        ready=True,
        minimum_precheap_soc_percent=20.0,
        state="protect",
    )

    allocations, evidence = helpers["_apply_floor_and_forecast_target"](
        state,
        plan,
        config=config,
        tariff=tariff,
        forecast_plan=forecast_plan,
    )

    assert allocations[low["valid_from"]] == 0.0
    assert sum(allocations.values()) <= 3.05 + 1e-9
    assert evidence["economic_export_floor_pence"] == 3.5
    assert evidence["forecast_floor_applied"] is True
    assert evidence["effective_precheap_target_soc_percent"] == 20.0


def test_high_confidence_forecast_detects_full_battery_solar_spill() -> None:
    helpers = _load_helpers()
    now = datetime(2026, 8, 22, 6, 0, tzinfo=UTC)
    forecast = SimpleNamespace(
        ready=True,
        confidence_percent=90.0,
        hourly=tuple(
            SimpleNamespace(
                timestamp=now + timedelta(hours=hour),
                solar_energy_kwh=4.0,
            )
            for hour in (6, 7, 8)
        ),
    )
    forecast_plan = SimpleNamespace(
        confidence_percent=90.0,
        expected_house_remaining_today_kwh=4.0,
    )
    learned = SimpleNamespace(typical_house_load_kw=0.5)
    config = SimpleNamespace(
        battery_capacity_kwh=10.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
    )

    projection = helpers["_forecast_spill_projection"](
        now=now,
        deadline=now.replace(hour=23, minute=30),
        soc_percent=95.0,
        config=config,
        forecast=forecast,
        forecast_plan=forecast_plan,
        learned=learned,
        effective_target_soc_percent=10.0,
    )

    assert projection["available"] is True
    assert projection["state"] == "spill_expected"
    assert projection["forecast_spill_kwh"] > 0.0
    assert projection["required_early_export_kwh"] > 0.0


def test_better_early_slot_retimes_later_export_without_increasing_total() -> None:
    helpers = _load_helpers()
    now = datetime(2026, 8, 22, 5, 30, tzinfo=UTC)
    early = _slot(now, 12.94)
    spill = _slot(now.replace(hour=14, minute=0), 9.0, allocation=1.0)
    state = {"today_slots": [early, spill]}
    plan = {
        "effective_discharge_kw": 7.0,
        "selected_slots": [
            {
                "valid_from": spill["valid_from"],
                "planned_battery_export_kwh": 1.0,
            }
        ],
    }
    allocations = {spill["valid_from"]: 1.0}
    forecast = SimpleNamespace(
        ready=True,
        confidence_percent=90.0,
        hourly=(
            SimpleNamespace(
                timestamp=now.replace(hour=14, minute=0),
                solar_energy_kwh=5.0,
            ),
        ),
    )
    forecast_plan = SimpleNamespace(
        confidence_percent=90.0,
        expected_house_remaining_today_kwh=2.0,
    )
    learned = SimpleNamespace(typical_house_load_kw=0.2)
    config = SimpleNamespace(
        battery_capacity_kwh=10.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        max_discharge_kw=7.0,
    )
    tariff = SimpleNamespace(
        offpeak_rate_pence=3.5,
        offpeak_start=SimpleNamespace(),
    )
    helpers["rolling"] = SimpleNamespace(
        _current_agile_soc=lambda state: 95.0,
        _current_house_headroom_kw=lambda self, config: 0.0,
    )
    helpers["agile"] = SimpleNamespace(
        _next_cheap=lambda moment, tariff: moment.replace(hour=23, minute=30)
    )

    reconciled, additions, evidence = helpers["_retime_for_solar_headroom"](
        object(),
        state,
        plan,
        allocations,
        now=now,
        config=config,
        tariff=tariff,
        forecast=forecast,
        forecast_plan=forecast_plan,
        learned=learned,
        effective_target_soc_percent=10.0,
    )

    assert evidence["active"] is True
    assert evidence["spill_reference_rate_pence"] == 9.0
    assert additions[early["valid_from"]] > 0.0
    assert abs(sum(reconciled.values()) - 1.0) <= 1e-9
    assert reconciled[spill["valid_from"]] < 1.0


def test_runtime_registration_is_canonical_and_event_priority_remains_later() -> None:
    source = COMPAT.read_text(encoding="utf-8")
    new_layer = '("agile_forecast_arbitrage", "install_forecast_arbitrage")'
    economic = '("agile_economic_opportunity", "install_economic_opportunity")'
    publication = '("agile_price_publication", "install_price_publication")'
    event_priority = '("agile_event_priority", "install_event_priority")'

    assert new_layer in source
    assert source.index(economic) < source.index(new_layer) < source.index(publication)
    assert source.index(new_layer) < source.index(event_priority)
    assert "agile_alpha8" not in MODULE.name


def test_forecast_arbitrage_cannot_enable_hardware_writes_or_bump_release() -> None:
    source = MODULE.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "commands_permitted = True" not in source
    assert "safe_to_write_hardware = True" not in source
    assert '"version": "0.8.0-alpha8.' in manifest
