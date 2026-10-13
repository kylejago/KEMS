"""Alpha9.92 export-commissioning rollback and unplugged-Ohme regressions.

These predicates are loaded from the production AST so the tests exercise
the actual code while keeping Home Assistant hardware dependencies isolated.
"""

from __future__ import annotations

import ast
import asyncio
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
        if isinstance(node, ast.FunctionDef) and node.name in {"_number", function}
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
    for field in (
        "work_mode",
        "min_soc_on_grid",
        "force_discharge_power",
        "export_power_limit",
    ):
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
    assert backend.count('or self._last_applied_action == "force_discharge"') == 5
    assert backend.count("or self._commissioning_restore_pending") >= 4
    assert source.count("if not _ev_confirmed_safe_for_export(snapshot):") == 2


def test_restoration_does_not_release_on_optimistic_ha_state_alone() -> None:
    """Regression for 13 Oct: sensor still 15%/6.4kW, HA mode already Self Use."""
    tree = ast.parse(BACKEND.read_text(encoding="utf-8"), filename=str(BACKEND))
    backend_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "FoxESSControlBackend"
    )
    method = next(
        node
        for node in backend_class.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_async_restore"
    )
    scope: dict[str, Any] = {
        "Any": Any,
        "_LOCAL_WORK_MODES": {"Self Use", "Feed-in First", "Back-up"},
        "_number": _function(BACKEND, "_number"),
        "_commissioning_restore_readback_matches": _function(
            BACKEND, "_commissioning_restore_readback_matches"
        ),
    }
    exec(
        compile(ast.Module(body=[method], type_ignores=[]), str(BACKEND), "exec"),
        scope,
    )
    restore = scope["_async_restore"]

    class Backend:
        _owned = True
        _commissioning_restore_pending = False
        _previous_work_mode = "Self Use"
        _previous_min_soc_on_grid = 10.0
        _previous_force_discharge_power_kw = 0.666
        _previous_export_power_limit_w = 14500.0
        _paid_export_stage_blocked = False
        _paid_export_live_proven = True
        _paid_export_stage_samples = 2
        _paid_export_stage_failures = 0
        _paid_export_stage_reason = None
        _last_applied_action = "force_discharge"
        _last_verified_min_soc_on_grid = None
        _last_verified_min_soc_at = None
        _last_write_result = ""
        saves = 0

        def __init__(self) -> None:
            self._hass = SimpleNamespace(
                states=SimpleNamespace(
                    get=lambda entity: SimpleNamespace(
                        state="Self Use" if entity == "work_mode" else "10"
                    )
                )
            )

        @staticmethod
        def _entity_id(_entities, name):
            return name

        async def _async_select(self, *args, **kwargs):
            return True

        async def _async_number(self, *args, **kwargs):
            return True

        async def _async_restore_paid_export_settings(self, *args, **kwargs):
            return True

        async def _async_save(self):
            self.saves += 1

    backend = Backend()
    contaminated = _baseline_entities()
    contaminated["work_mode"]["normalised_observation"] = "Feed-in First"
    contaminated["min_soc_on_grid"]["normalised_observation"] = 15.0
    contaminated["export_power_limit"]["normalised_observation"] = 6400.0
    writes: list[str] = []
    confirmed = asyncio.run(
        restore(backend, contaminated, writes, verify_physical_baseline=True)
    )
    assert confirmed is False
    assert backend._owned is True
    assert backend._previous_min_soc_on_grid == 10.0
    assert backend._previous_export_power_limit_w == 14500.0
    assert (
        "awaiting a separate FoxESS physical readback scan"
        in backend._last_write_result
    )

    confirmed = asyncio.run(
        restore(backend, _baseline_entities(), writes, verify_physical_baseline=True)
    )
    assert confirmed is True
    assert backend._owned is False
    assert backend._last_applied_action is None

    # Even when the *first* snapshot looks restored, a second scan is mandatory
    # before the controller may finalize the test and reacquire FoxESS ownership.
    another = Backend()
    first_scan = asyncio.run(
        restore(another, _baseline_entities(), [], verify_physical_baseline=True)
    )
    assert first_scan is False
    assert another._owned is True
    assert another._commissioning_restore_pending is True
    second_scan = asyncio.run(
        restore(another, _baseline_entities(), [], verify_physical_baseline=True)
    )
    assert second_scan is True
    assert another._owned is False


def _paid_baseline_entities() -> dict[str, dict[str, Any]]:
    items = _baseline_entities()
    for item in items.values():
        item["device_id"] = "same-reviewed-foxess-device"
    items["min_soc_on_grid"]["normalised_observation"] = 15.0
    items["export_power_limit"]["normalised_observation"] = 6400.0
    return items


def _paid_baseline_eligible(entities=None, **overrides: Any) -> bool:
    predicate = _function(BACKEND, "_paid_agile_contaminated_baseline_verified")
    values = {
        "original_mode": "Feed-in First",
        "original_min_soc": 15.0,
        "original_discharge_power": 0.666,
        "original_export_limit_w": 6400.0,
        "last_action": "self_use",
        "minimum_min_soc": 10.0,
        "normal_export_reserve": 15.0,
        "ev_connected": False,
        "ev_charging": False,
        "ev_power_kw": 0.0,
    }
    values.update(overrides)
    return predicate(_paid_baseline_entities() if entities is None else entities, **values)


def test_paid_agile_can_repair_only_exact_13_october_rollback_signature() -> None:
    assert _paid_baseline_eligible()


def test_paid_baseline_repair_rejects_partial_or_different_evidence() -> None:
    for changes in (
        {"original_mode": "Self Use"},
        {"original_min_soc": 10.0},
        {"original_discharge_power": 2.0},
        {"original_export_limit_w": 14500.0},
        {"last_action": "force_discharge"},
        {"minimum_min_soc": 15.0},
        {"normal_export_reserve": 10.0},
        {"ev_connected": None},
        {"ev_connected": True},
        {"ev_charging": None},
        {"ev_charging": True},
        {"ev_power_kw": None},
        {"ev_power_kw": 3.0},
    ):
        assert not _paid_baseline_eligible(**changes)
    for field in (
        "work_mode",
        "min_soc_on_grid",
        "force_discharge_power",
        "export_power_limit",
    ):
        entities = _paid_baseline_entities()
        entities[field]["status"] = "WAIT"
        assert not _paid_baseline_eligible(entities)
        entities = _paid_baseline_entities()
        entities[field]["device_id"] = "different-foxess-device"
        assert not _paid_baseline_eligible(entities)
    for field in ("min_soc_on_grid", "export_power_limit"):
        entities = _paid_baseline_entities()
        entities[field]["observation_source"] = "command_entity"
        assert not _paid_baseline_eligible(entities)


def test_paid_baseline_repair_does_not_alter_no_paid_export_policy() -> None:
    backend = BACKEND.read_text(encoding="utf-8")
    assert "not no_paid_export_mode" in backend
    assert "export_tariff_type_from_options(coordinator.entry.options)" in backend
    assert "== EXPORT_TARIFF_TYPE_AGILE" in backend
    assert "and not commissioning_export_test" in backend
    assert "paid_activation_baseline_blocked" in backend
    assert "self._previous_work_mode = \"Self Use\"" in backend
    assert "self._previous_min_soc_on_grid = 10.0" in backend
    assert "self._previous_export_limit_w = 14500.0" not in backend
    assert "no_paid_export_mode and not commissioning_export_test" in backend
