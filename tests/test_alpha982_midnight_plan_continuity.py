"""Alpha9.82 regression for continuous Today-to-Tomorrow SOC presentation."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
CONTINUITY = KEMS / "agile_tomorrow_display_continuity.py"
RUNTIME = KEMS / "agile_smart_export_runtime.py"


def _function():
    source = CONTINUITY.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {
        "_number",
        "_dt",
        "_component",
        "_required_battery_component",
        "_reconcile_tomorrow_display_continuity",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    ]
    slot_flow_source = (KEMS / "kems_core" / "slot_flow.py").read_text(
        encoding="utf-8"
    )
    slot_tree = ast.parse(slot_flow_source)
    slot_nodes = [
        node
        for node in slot_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_number", "_route_label", "build_slot_flow"}
    ]
    namespace = {
        "Any": object,
        "datetime": __import__("datetime").datetime,
        "math": __import__("math"),
        "SimulationConfig": object,
    }
    slot_namespace = {"Any": object, "math": __import__("math"), "_EPSILON": 0.0005}
    slot_module = ast.Module(body=slot_nodes, type_ignores=[])
    ast.fix_missing_locations(slot_module)
    exec(compile(slot_module, "slot_flow.py", "exec"), slot_namespace)
    namespace["build_slot_flow"] = slot_namespace["build_slot_flow"]
    namespace["_EPSILON"] = 1e-6
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, CONTINUITY.as_posix(), "exec"), namespace)
    return namespace["_reconcile_tomorrow_display_continuity"]


def _config():
    return SimpleNamespace(
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )


def _state():
    return {
        "today_slots": [
            {
                "label": "23:30",
                "valid_from": "2026-10-06T22:30:00+00:00",
                "valid_to": "2026-10-06T23:00:00+00:00",
                "flow_estimated_soc_percent": 20.9,
                "ending_soc_percent": None,
            }
        ],
        "tomorrow_slots": [
            {
                "label": "00:00",
                "valid_from": "2026-10-06T23:00:00+00:00",
                "valid_to": "2026-10-06T23:30:00+00:00",
                "grid_import_kwh": 4.303,
                "solar_generation_kwh": 0.0,
                "solar_to_home_kwh": 0.0,
                "solar_to_battery_kwh": 0.0,
                "solar_export_kwh": 0.0,
                "grid_to_battery_kwh": 3.325,
                "battery_to_home_kwh": 0.0,
                "battery_export_kwh": 0.0,
                "ending_soc_percent": 83.3,
                "flow_estimated_soc_percent": 83.3,
                "flow_grid_to_battery_kwh": 0.0,
                "flow_battery_charge_kwh": 0.0,
                "flow_battery_action": "IDLE",
            },
            {
                "label": "00:30",
                "valid_from": "2026-10-06T23:30:00+00:00",
                "valid_to": "2026-10-07T00:00:00+00:00",
                "grid_import_kwh": 4.303,
                "solar_generation_kwh": 0.0,
                "solar_to_home_kwh": 0.0,
                "solar_to_battery_kwh": 0.0,
                "solar_export_kwh": 0.0,
                "grid_to_battery_kwh": 3.325,
                "battery_to_home_kwh": 0.0,
                "battery_export_kwh": 0.0,
                "ending_soc_percent": 89.2,
                "flow_estimated_soc_percent": 89.2,
                "flow_grid_to_battery_kwh": 0.0,
                "flow_battery_charge_kwh": 0.0,
                "flow_battery_action": "IDLE",
            },
        ],
    }


def test_tomorrow_inherits_final_today_soc_and_advances_by_real_charge() -> None:
    state = _state()
    corrected = _function()(state, config=_config())

    assert corrected == 2
    first, second = state["tomorrow_slots"]
    expected_first = 20.9 + 3.325 / 56.42 * 100.0
    expected_second = expected_first + 3.325 / 56.42 * 100.0
    assert first["flow_estimated_soc_percent"] == pytest.approx(
        round(expected_first, 1)
    )
    assert second["flow_estimated_soc_percent"] == pytest.approx(
        round(expected_second, 1)
    )
    assert first["flow_estimated_soc_percent"] < 30.0
    assert first["pre_midnight_handoff_flow_soc_percent"] == 83.3
    assert first["flow_soc_midnight_rebased"] is True


def test_grid_charge_is_not_presented_as_battery_idle() -> None:
    state = _state()
    _function()(state, config=_config())
    first = state["tomorrow_slots"][0]

    assert first["flow_grid_to_battery_kwh"] == pytest.approx(3.325)
    assert first["flow_battery_charge_kwh"] == pytest.approx(3.325)
    assert first["flow_battery_action"] == "CHARGE"
    assert first["flow_checks"]["grid_charge_within_import"] is True


def test_boundary_mismatch_fails_closed_without_rewriting_tomorrow() -> None:
    state = _state()
    state["today_slots"][0]["valid_to"] = "2026-10-06T22:59:00+00:00"
    before = state["tomorrow_slots"][0]["flow_estimated_soc_percent"]

    assert _function()(state, config=_config()) == 0
    assert state["tomorrow_slots"][0]["flow_estimated_soc_percent"] == before
    diagnostic = state["tomorrow_display_continuity"]
    assert diagnostic["active"] is False
    assert "No exact Today slot" in diagnostic["reason"]


def test_unknown_battery_energy_stops_without_inventing_flow() -> None:
    state = _state()
    state["tomorrow_slots"][1]["battery_export_kwh"] = None
    # Presentation zero must never turn an unknown authoritative value into zero.
    state["tomorrow_slots"][1]["flow_battery_export_kwh"] = 0.0
    old_second = state["tomorrow_slots"][1]["flow_estimated_soc_percent"]

    assert _function()(state, config=_config()) == 1
    assert state["tomorrow_slots"][1]["flow_estimated_soc_percent"] == old_second
    assert "components unavailable" in state["tomorrow_display_continuity"][
        "stopped_reason"
    ]


def test_alpha982_runtime_installs_continuity_after_safety_floor() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    assert "build_tomorrow_display_continuity_manager" in source
    assert "_safety_floor_manager = build_safety_floor_manager(" in source
    assert (
        "EfficientAgileSmartExportManager = "
        "build_tomorrow_display_continuity_manager(_safety_floor_manager)"
    ) in source


def test_alpha982_continuity_is_reporting_only() -> None:
    source = CONTINUITY.read_text(encoding="utf-8")
    assert '"hardware_writes": "blocked"' in source
    assert "services.async_call" not in source
    assert "async_call(" not in source
    assert "foxess" not in source.lower()