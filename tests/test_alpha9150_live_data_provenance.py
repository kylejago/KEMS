"""Alpha9.152: live dashboard never presents the twin as physical authority."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
SOURCE = KEMS / "agile_slots_state.py"


def _helpers() -> dict[str, Any]:
    tree = ast.parse(SOURCE.read_text())
    methods = {"_utc_time", "_finite_nonnegative", "_guarded_live_summary"}
    module = ast.Module(
        body=[
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in methods
        ],
        type_ignores=[],
    )
    namespace = {"UTC": UTC, "datetime": datetime, "timedelta": timedelta, "Any": Any}
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    return namespace


def _state(at: datetime, *, physical: bool = True) -> dict[str, Any]:
    return {
        "rolling_export_plan": {
            "available": True,
            "generated_at": at.isoformat(),
            "planning_soc_percent": 35.021 if physical else 43.612,
            "planning_soc_source": (
                "verified FoxESS physical lower bound"
                if physical
                else "independent digital twin"
            ),
            "physical_planning_evidence": {"available": physical},
            "physical_ac_export_budget_applied": physical,
            "physical_ac_export_budget_kwh": 4.487 if physical else 17.8,
            "simulated_soc_percent": 43.612,
            "simulated_exportable_energy_kwh": 17.8,
        }
    }


def _coordinator(at: datetime, *, permitted: bool = True):
    return SimpleNamespace(
        data=SimpleNamespace(
            snapshot=SimpleNamespace(timestamp=at),
            control=SimpleNamespace(
                commands_permitted=permitted,
                desired_battery_export_power_kw=6.071,
            ),
        ),
        _agile_live_reserve_status={"status": "permitted_with_physical_house_budget"},
    )


def test_live_summary_uses_final_controller_and_physical_ac_budget() -> None:
    at = datetime.now(UTC)
    values = _helpers()["_guarded_live_summary"](_coordinator(at), _state(at))
    assert values["final_control_export_target_kw"] == 6.071
    assert values["physical_budget_exportable_ac_kwh"] == 4.487
    assert values["verified_physical_soc_lower_bound_percent"] == 35.02
    assert values["control_authority"] == "final guarded KEMS physical control"
    assert values["hardware_writes"] == "blocked"
    assert values["reporting_only"] is True


def test_twin_values_cannot_become_live_physical_soc_or_budget() -> None:
    at = datetime.now(UTC)
    values = _helpers()["_guarded_live_summary"](
        _coordinator(at), _state(at, physical=False)
    )
    assert values["final_control_export_target_kw"] == 6.071
    assert values["physical_budget_exportable_ac_kwh"] is None
    assert values["verified_physical_soc_lower_bound_percent"] is None


def test_stale_observation_or_unpermitted_commands_stay_unavailable() -> None:
    at = datetime.now(UTC)
    helper = _helpers()["_guarded_live_summary"]
    stale = helper(_coordinator(at - timedelta(minutes=3)), _state(at))
    assert stale["final_control_export_target_kw"] is None
    assert stale["physical_budget_exportable_ac_kwh"] is None

    forbidden = helper(_coordinator(at, permitted=False), _state(at))
    assert forbidden["final_control_export_target_kw"] is None
    assert forbidden["physical_budget_exportable_ac_kwh"] == 4.487

    old_plan = helper(_coordinator(at), _state(at - timedelta(minutes=8)))
    assert old_plan["physical_budget_exportable_ac_kwh"] is None
    assert old_plan["verified_physical_soc_lower_bound_percent"] is None


def test_home_uses_physical_guard_not_simulator_and_costs_are_estimates() -> None:
    main = (ROOT / "dashboards" / "kems_master_dashboard.yaml").read_text()
    packaged = (KEMS / "kems_master_dashboard.yaml").read_text()
    assert main == packaged
    home = main.split("  - title: Live Data", 1)[0]
    assert "live_control_summary" in home
    assert "final_control_export_target_kw" in home
    assert "physical_budget_exportable_ac_kwh" in home
    assert "sensor.kems_target_battery_export_power" not in home
    assert "sensor.kems_exportable_battery_energy_remaining" not in home
    assert "sensor.kems_battery_state_of_charge" in home
    assert "sensor.kems_current_export_rate" in home
    assert "Estimated Agile export credit" in home
    assert "not confirmed Octopus settlement" in home


def test_sensor_live_fields_read_snapshot_not_simulated_soc() -> None:
    sensors = (KEMS / "sensor.py").read_text()
    assert "value_fn=lambda data: data.snapshot.battery_soc" in sensors
    assert "value_fn=lambda data: data.snapshot.grid_export_kw" in sensors
    assert "value_fn=lambda data: data.snapshot.solar_power_kw" in sensors
    assert "value_fn=lambda data: data.simulation.simulated_battery_soc" in sensors
    assert "physical_ac_export_budget_applied" in SOURCE.read_text()
    assert json.loads((KEMS / "manifest.json").read_text())["version"] == (
        "0.9.0-alpha9.161"
    )
