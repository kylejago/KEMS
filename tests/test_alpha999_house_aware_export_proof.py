"""Alpha9.99: fail-closed household-aware paid-export staging regressions.

Extract the production functions by AST to exercise physical control math
without importing Home Assistant or creating any real inverter writes.
"""

from __future__ import annotations

import ast
import asyncio
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BACKEND = (
    Path(__file__).parents[1] / "custom_components" / "kems" / "foxess_control_backend.py"
)


def _production():
    tree = ast.parse(BACKEND.read_text(encoding="utf-8"), filename=str(BACKEND))
    wanted = {"_number", "_bounded_paid_export_discharge_setpoint"}
    methods = {"async_setup", "_async_save", "_async_observe_paid_export_stage"}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    backend = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "FoxESSControlBackend"
    )
    selected.extend(
        node for node in backend.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in methods
    )
    assert len(selected) == len(wanted) + len(methods)
    scope = {
        "Any": Any,
        "isfinite": isfinite,
        "_PAID_EXPORT_STAGE_KW": 1.0,
        "_PAID_EXPORT_MIN_GRID_EXPORT_KW": 0.2,
        "_PAID_EXPORT_MIN_BATTERY_DISCHARGE_KW": 0.25,
        "_PAID_EXPORT_MAX_SOLAR_KW": 0.5,
        "_PAID_EXPORT_PROOF_SAMPLES": 2,
        "_PAID_EXPORT_FAILURE_SAMPLES": 3,
        "_PAID_EXPORT_PROOF_PROTOCOL": 2,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(BACKEND), "exec"), scope)
    return scope


PRODUCTION = _production()
SETPOINT = PRODUCTION["_bounded_paid_export_discharge_setpoint"]
OBSERVE = PRODUCTION["_async_observe_paid_export_stage"]
SETUP = PRODUCTION["async_setup"]
SAVE = PRODUCTION["_async_save"]


def _setpoint(**overrides):
    data = {
        "requested_grid_export_kw": 2.8,
        "planned_total_discharge_kw": 4.0,
        "observed_house_load_kw": 1.2,
        "observed_solar_kw": 0.0,
        "max_discharge_kw": 10.0,
        "inverter_limit_kw": 10.0,
        "effective_export_limit_kw": 7.0,
        "staging": True,
    }
    data.update(overrides)
    return SETPOINT(**data)


def test_proof_commands_one_kw_net_export_not_one_kw_total_discharge():
    assert _setpoint() == 2.2
    assert _setpoint(staging=False) == 4.0
    assert _setpoint(observed_house_load_kw=0) == 1.0


def test_export_ceiling_limits_net_export_without_truncating_house_power():
    assert _setpoint(
        requested_grid_export_kw=9,
        planned_total_discharge_kw=9,
        observed_house_load_kw=1.2,
        effective_export_limit_kw=7,
        staging=False,
    ) == 8.2
    assert _setpoint(
        requested_grid_export_kw=9,
        planned_total_discharge_kw=9,
        observed_house_load_kw=1.2,
        effective_export_limit_kw=7,
        staging=True,
    ) == 2.2


def test_solar_and_inverter_limits_remain_bounded():
    assert _setpoint(observed_house_load_kw=1.2, observed_solar_kw=1.5) == 1.0
    assert _setpoint(max_discharge_kw=1.6) == 1.6
    assert _setpoint(inverter_limit_kw=1.4) == 1.4


def test_unverified_or_insufficient_headroom_never_commands_discharge():
    assert _setpoint(planned_total_discharge_kw=1.2) is None
    assert _setpoint(observed_house_load_kw=8.0, inverter_limit_kw=7.0) is None
    assert _setpoint(observed_house_load_kw=None) is None
    assert _setpoint(observed_house_load_kw=float("nan")) is None
    assert _setpoint(observed_solar_kw=-1.0) is None
    assert _setpoint(effective_export_limit_kw=0.0) is None
    assert _setpoint(requested_grid_export_kw=0.1) is None


class _MemoryStore:
    def __init__(self, value):
        self.value = dict(value)
        self.saves = []

    async def async_load(self):
        return dict(self.value)

    async def async_save(self, payload):
        self.saves.append(dict(payload))
        self.value = dict(payload)


def _backend(store=None):
    backend = SimpleNamespace(
        _store=store,
        _owned=False,
        _previous_work_mode=None,
        _previous_min_soc_on_grid=None,
        _previous_force_discharge_power_kw=None,
        _previous_export_power_limit_w=None,
        _paid_export_live_proven=False,
        _paid_export_stage_samples=0,
        _paid_export_stage_failures=0,
        _paid_export_stage_blocked=False,
        _paid_export_stage_reason=None,
        _last_applied_action=None,
        _last_verified_min_soc_on_grid=None,
        _last_verified_min_soc_at=None,
    )
    backend._async_save = lambda: SAVE(backend)
    return backend


def test_legacy_failure_latch_requalified_once_preserving_rollback_baseline():
    store = _MemoryStore({
        "paid_export_stage_blocked": True,
        "paid_export_stage_reason": "Failed legacy 1 kW proof",
        "owned": True,
        "previous_work_mode": "Self Use",
        "previous_min_soc_on_grid": 10,
        "previous_force_discharge_power_kw": 0.666,
        "previous_export_power_limit_w": 7000,
        "last_applied_action": "force_discharge",
        "last_verified_min_soc_on_grid": 10,
        "last_verified_min_soc_at": "2026-10-14T23:00:00+00:00",
    })
    backend = _backend(store)
    asyncio.run(SETUP(backend))
    assert not backend._paid_export_stage_blocked
    assert not backend._paid_export_live_proven
    assert store.saves and store.value["paid_export_proof_protocol"] == 2
    assert store.value["previous_work_mode"] == "Self Use"
    assert store.value["previous_min_soc_on_grid"] == 10
    assert store.value["last_applied_action"] == "force_discharge"
    assert store.value["last_verified_min_soc_on_grid"] == 10

    store.value["paid_export_stage_blocked"] = True
    backend_again = _backend(store)
    count = len(store.saves)
    asyncio.run(SETUP(backend_again))
    assert backend_again._paid_export_stage_blocked
    assert len(store.saves) == count


def test_home_demand_absorbing_battery_does_not_count_as_direction_failure():
    backend = _backend()
    backend._last_applied_action = "force_discharge"
    async def save_observation():
        return None
    backend._async_save = save_observation
    snapshot = SimpleNamespace(
        stale_fields=(),
        house_load_kw=1.2,
        solar_power_kw=0.0,
        battery_power_kw=1.0,
        grid_export_kw=0.0,
    )
    entities = {
        "work_mode": {"normalised_observation": "Force Discharge"},
        "export_power_limit": {"normalised_observation": 7000.0},
    }
    config = SimpleNamespace(
        battery_power_positive_is_discharge=True,
        export_limit_kw=7.0,
    )
    asyncio.run(OBSERVE(backend, snapshot=snapshot, entities=entities, config=config))
    assert backend._paid_export_stage_failures == 0
    assert not backend._paid_export_stage_blocked
    assert "house demand" in backend._paid_export_stage_reason

    snapshot.battery_power_kw = 2.2
    snapshot.grid_export_kw = 0.9
    asyncio.run(OBSERVE(backend, snapshot=snapshot, entities=entities, config=config))
    assert backend._paid_export_stage_samples == 1
    asyncio.run(OBSERVE(backend, snapshot=snapshot, entities=entities, config=config))
    assert backend._paid_export_live_proven


def test_decisive_direction_mismatch_still_latches_after_three_samples():
    backend = _backend()
    backend._last_applied_action = "force_discharge"
    calls = []
    async def record():
        calls.append(True)
    backend._async_save = record
    snapshot = SimpleNamespace(
        stale_fields=(),
        house_load_kw=1.0,
        solar_power_kw=0.0,
        battery_power_kw=2.5,
        grid_export_kw=0.0,
    )
    entities = {
        "work_mode": {"normalised_observation": "Force Discharge"},
        "export_power_limit": {"normalised_observation": 7000.0},
    }
    config = SimpleNamespace(
        battery_power_positive_is_discharge=True,
        export_limit_kw=7.0,
    )
    for _ in range(3):
        asyncio.run(OBSERVE(backend, snapshot=snapshot, entities=entities, config=config))
    assert backend._paid_export_stage_blocked
    assert backend._paid_export_stage_failures == 3
    assert calls
