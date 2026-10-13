"""Alpha9.92 export-commissioning rollback and unplugged-Ohme regressions.

These predicates are loaded from the production AST so the tests exercise
the actual code while keeping Home Assistant hardware dependencies isolated.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
BACKEND = KEMS / "foxess_control_backend.py"
TEST = KEMS / "export_commissioning_test.py"


def _function(path: Path, function: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_number", function}
    ]
    assert any(node.name == function for node in selected)
    namespace: dict[str, Any] = {"Any": Any}
    exec(
        compile(
            ast.Module(body=selected, type_ignores=[]),
            filename=str(path),
            mode="exec",
        ),
        namespace,
    )
    return namespace[function]


def _baseline_entities() -> dict[str, dict[str, Any]]:
    return {
        "work_mode": {
            "status": "PASS",
            "observation_source": "command_entity",
            "normalised_observation": "Self Use",
        },
        "min_soc_on_grid": {
            "status": "PASS",
            "observation_source": "sensor_readback",
            "normalised_observation": 10.0,
        },
        "force_discharge_power": {
            "status": "PASS",
            "observation_source": "command_entity",
            "normalised_observation": 0.666,
        },
        "export_power_limit": {
            "status": "PASS",
            "observation_source": "sensor_readback",
            "normalised_observation": 14500.0,
        },
    }


def _matches(entities: dict[str, dict[str, Any]]) -> bool:
    check = _function(BACKEND, "_commissioning_restore_readback_matches")
    return check(
        entities,
        work_mode="Self Use",
        min_soc_on_grid=10.0,
        force_discharge_power_kw=0.666,
        export_power_limit_w=14500.0,
    )


def test_real_baseline_readback_can_release_commissioning_ownership() -> None:
    assert _matches(_baseline_entities())


def test_aborted_export_must_not_capture_interim_feed_in_and_15_percent() -> None:
    entities = _baseline_entities()
    entities["work_mode"]["normalised_observation"] = "Feed-in First"
    entities["min_soc_on_grid"]["normalised_observation"] = 15.0
    entities["export_power_limit"]["normalised_observation"] = 6400.0
    assert not _matches(entities)


def test_optimistic_number_state_cannot_replace_physical_sensor_readback() -> None:
    for field in ("min_soc_on_grid", "export_power_limit"):
        entities = _baseline_entities()
        entities[field]["observation_source"] = "command_entity"
        assert not _matches(entities)


def test_partial_missing_or_failed_restore_bindings_never_release() -> None:
    for field in ("work_mode", "min_soc_on_grid", "force_discharge_power", "export_power_limit"):
        entities = _baseline_entities()
        del entities[field]
        assert not _matches(entities)
        entities = _baseline_entities()
        entities[field]["status"] = "FAIL"
        assert not _matches(entities)


def test_refuse_release_while_export_limit_has_not_restored() -> None:
    entities = _baseline_entities()
    entities["export_power_limit"]["normalised_observation"] = 6400.0
    assert not _matches(entities)


def _ev(**changes: Any) -> SimpleNamespace:
    state: dict[str, Any] = {
        "ev_connected": False,
        "ev_charging": False,
        "ev_power_kw": 0.0,
        "ev_power_age_seconds": 1.0,
        "stale_fields": (),
    }
    state.update(changes)
    return SimpleNamespace(**state)


def test_unplugged_ohme_is_safe_without_demanding_charge_status_repetition() -> None:
    ready = _function(TEST, "_ev_confirmed_safe_for_export")
    assert ready(_ev())
    assert ready(_ev(ev_charging=None))  # Explicit unplugged plus fresh zero power
    assert ready(_ev(ev_power_kw=None, ev_charging=False))


def test_ohme_uncertainty_and_positive_load_must_still_stop_export() -> None:
    ready = _function(TEST, "_ev_confirmed_safe_for_export")
    assert not ready(_ev(ev_connected=None))
    assert not ready(_ev(ev_connected=True))
    assert not ready(_ev(ev_charging=True))
    assert not ready(_ev(ev_power_kw=2.5))
    assert not ready(_ev(ev_charging=None, ev_power_kw=None))
    assert not ready(_ev(ev_charging=None, ev_power_age_seconds=None))
    assert not ready(_ev(ev_charging=None, ev_power_age_seconds=181.0))
    assert not ready(_ev(ev_charging=None, stale_fields=("ev_power_kw",)))


def test_manual_test_requires_a_postwrite_physical_restoration_snapshot() -> None:
    backend = BACKEND.read_text(encoding="utf-8")
    source = TEST.read_text(encoding="utf-8")
    restore = backend.split("async def _async_restore(", 1)[1].split(
        "async def async_shutdown(", 1
    )[0]
    assert "verify_physical_baseline: bool = False" in restore
    assert "_commissioning_restore_readback_matches(" in restore
    assert "self._owned = False" in restore
    assert restore.index("_commissioning_restore_readback_matches(") < restore.index(
        "self._owned = False"
    )
    assert "verify_physical_baseline=bool(" in backend
    assert backend.count("commissioning_export_test or force_restore") >= 4
    assert source.count("if not _ev_confirmed_safe_for_export(snapshot):") == 2
