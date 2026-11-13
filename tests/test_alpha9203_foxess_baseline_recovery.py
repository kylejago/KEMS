"""Alpha9.203: strict same-KH7 recovery for 13 Nov paid-export rollback latch."""

from __future__ import annotations

import ast
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
BACKEND = ROOT / "custom_components" / "kems" / "foxess_control_backend.py"


def _function(name: str, namespace: dict[str, Any] | None = None):
    source = BACKEND.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(BACKEND))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    scope: dict[str, Any] = {
        "Any": Any,
        "isfinite": math.isfinite,
    }
    if namespace:
        scope.update(namespace)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(BACKEND), "exec"), scope)
    return scope[name]


def _entities() -> dict[str, dict[str, Any]]:
    device = "reviewed-kh7"
    return {
        "work_mode": {
            "status": "PASS",
            "device_id": device,
            "normalised_observation": "Self Use",
            "observation_source": "command_entity",
        },
        "min_soc_on_grid": {
            "status": "PASS",
            "device_id": device,
            "normalised_observation": 10.0,
            "observation_source": "sensor_readback",
        },
        "force_discharge_power": {
            "status": "PASS",
            "device_id": device,
            "normalised_observation": 0.997,
            "observation_source": "command_entity",
        },
        "export_power_limit": {
            "status": "PASS",
            "device_id": device,
            "normalised_observation": 7000.0,
            "observation_source": "sensor_readback",
        },
    }


def _check(entities=None, **overrides: Any) -> bool:
    numeric = _function("_number")
    check = _function(
        "_paid_agile_owned_stage_baseline_verified",
        {"_number": numeric},
    )
    evidence = {
        "original_mode": "Feed-in First",
        "original_min_soc": 15.0,
        "original_discharge_power": 0.997,
        "original_export_limit_w": 7000.0,
        "last_action": "self_use",
        "minimum_min_soc": 10.0,
        "normal_export_reserve": 15.0,
        "ev_connected": False,
        "ev_charging": False,
        "ev_power_kw": 0.0,
    }
    evidence.update(overrides)
    return check(_entities() if entities is None else entities, **evidence)


def test_exact_13_nov_kh7_persisted_signature_can_repair_metadata() -> None:
    assert _check()


def test_not_a_generic_feed_in_first_restore_override() -> None:
    for change in (
        {"original_mode": "Self Use"},
        {"original_min_soc": 10.0},
        {"original_discharge_power": 0.666},
        {"original_discharge_power": 1.1},
        {"original_export_limit_w": 6400.0},
        {"original_export_limit_w": 14500.0},
        {"last_action": "force_discharge"},
        {"last_action": None},
        {"minimum_min_soc": 15.0},
        {"normal_export_reserve": 10.0},
        {"ev_connected": True},
        {"ev_connected": None},
        {"ev_charging": True},
        {"ev_power_kw": 1.0},
        {"ev_power_kw": None},
        {"ev_power_kw": math.nan},
        {"original_discharge_power": math.inf},
    ):
        assert not _check(**change), change


def test_no_optimistic_sensor_or_cross_device_evidence() -> None:
    for key in _entities():
        for operation in ("missing", "failed", "cross_device", "missing_device"):
            entities = _entities()
            if operation == "missing":
                del entities[key]
            elif operation == "failed":
                entities[key]["status"] = "WAIT"
            elif operation == "cross_device":
                entities[key]["device_id"] = "other-inverter"
            else:
                entities[key]["device_id"] = None
            assert not _check(entities), (key, operation)
    for key in ("min_soc_on_grid", "export_power_limit"):
        entities = _entities()
        entities[key]["observation_source"] = "command_entity"
        assert not _check(entities)


def test_live_value_mismatch_or_unavailable_prevents_recovery() -> None:
    for key, bad in (
        ("work_mode", "Feed-in First"),
        ("min_soc_on_grid", 15.0),
        ("min_soc_on_grid", None),
        ("force_discharge_power", 1.5),
        ("export_power_limit", 6400.0),
        ("export_power_limit", math.nan),
    ):
        entities = _entities()
        entities[key]["normalised_observation"] = bad
        assert not _check(entities), (key, bad)


def test_existing_historic_recovery_preserved_and_new_path_agile_only() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    assert "def _paid_agile_contaminated_baseline_verified(" in source
    assert "def _paid_agile_owned_stage_baseline_verified(" in source
    assert "and _paid_agile_verified_owned_baseline_recovery(" in source
    control = source.split("# Alpha9.92: repair only", 1)[1].split(
        "decision = assess_foxess_control_write_authority", 1
    )[0]
    for gate in (
        "not no_paid_export_mode",
        "== EXPORT_TARIFF_TYPE_AGILE",
        "not commissioning_export_test",
        "not force_restore",
        "self._owned",
        'self._last_applied_action == "self_use"',
        "not self._commissioning_restore_pending",
        "binding_ready",
        "technical_ready",
        "version_matches",
        "bool(control.data_fresh)",
        "bool(control.plan_safe)",
        "bool(control.grid_available)",
        "not bool(control.island_mode_active)",
    ):
        assert gate in control
    assert "self._previous_work_mode = \"Self Use\"" in control
    assert "self._previous_min_soc_on_grid = 10.0" in control
    assert "await self._async_save()" in control
    assert "_paid_agile_owned_stage_baseline_verified" not in (
        source.split("async def _async_restore(", 1)[1].split(
            "async def async_shutdown(", 1
        )[0]
    )
