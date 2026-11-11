"""Live Agile publication coalescing preserves final entity payload and exceptions.

Tests execute the actual three production async_update methods extracted from
their owning classes, with the Home Assistant transport and numerical routines
represented by deterministic in-memory stubs. No hardware calls are made.
"""

from __future__ import annotations

import ast
import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from textwrap import indent
from time import perf_counter

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


def _method(filename: str, class_name: str) -> str:
    source = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    owner = next(
        node
        for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method = next(
        node
        for node in owner.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_update"
    )
    return ast.unparse(method)


class _Base:
    def __init__(self):
        self._state = {}
        self.published = []
        self._alpha850_live_solar_tracker = None
        self._alpha850_live_solar_dirty = False

    @property
    def state(self):
        return deepcopy(self._state)

    def _publish(self, state):
        self.published.append(deepcopy(state))

    async def _save_alpha850_live_solar_tracker(self):
        self._alpha850_live_solar_dirty = False

    async def async_update(
        self, *, records, now, config, learned, forecast, forecast_plan, tariff
    ):
        self._state = {
            "generated_at": now.isoformat(),
            "records": deepcopy(records),
            "simulated_import_rate": tariff["price"],
            "forecast_name": forecast["name"],
            "slot_soc": learned["soc"],
        }
        return self.state


def _production_classes():
    def future(_self, state, *, now, **_kwargs):
        state["future"] = {
            "at": now.isoformat(),
            "next_import_rate": state["simulated_import_rate"],
        }
        return {"future": deepcopy(state["future"])}

    def attach(state, *, now, future_today):
        state["flow_contract"] = {
            "valid_at": now.isoformat(),
            "future": deepcopy(future_today),
        }

    def capture(state, *, now):
        return {"at": now.isoformat(), "price": state["simulated_import_rate"]}

    def active(state, *, now, config):
        if state["records"] and state["records"][0].get("fail_canonical"):
            raise RuntimeError("canonical overlay unavailable")
        state["active"] = {
            "rate": state["simulated_import_rate"],
            "limit": config["limit"],
        }

    def advance(tracker, state, *, now):
        return {"day": now.date().isoformat(), "flow": state["flow_contract"]}, False

    def elapsed(state, *, tracker, now):
        state["solar_elapsed"] = {"day": tracker["day"], "generated": now.isoformat()}

    def rebase(state, *, now, config):
        if state["records"] and state["records"][0].get("fail_solar"):
            raise RuntimeError("solar rebasing unavailable")
        state["soc_display"] = {"soc": state["slot_soc"], "limit": config["limit"]}

    namespace = {
        "Base": _Base,
        "perf_counter": perf_counter,
        "_future_today_projection": future,
        "_attach_flow_contract": attach,
        "_capture_live_replay_accounting": capture,
        "_active_slot_from_routing": active,
        "_advance_tracker": advance,
        "_apply_elapsed_solar_accounting": elapsed,
        "_rebase_display_soc": rebase,
    }
    code = "from __future__ import annotations\n"
    for classname, superclass, filename, owner in (
        (
            "Flow",
            "Base",
            "agile_flow_presentation.py",
            "FlowPresentationAgileSmartExportManager",
        ),
        (
            "Canonical",
            "Flow",
            "agile_canonical_flow_accounting.py",
            "CanonicalFlowAccountingAgileSmartExportManager",
        ),
        (
            "Solar",
            "Canonical",
            "agile_live_solar_soc_continuity.py",
            "LiveSolarSocContinuityAgileSmartExportManager",
        ),
    ):
        code += f"class {classname}({superclass}):\n"
        code += indent(_method(filename, owner), "    ") + "\n"
    exec(compile(code, "<production-agile-update>", "exec"), namespace)
    return namespace["Flow"], namespace["Canonical"], namespace["Solar"]


def _run(manager, *, now=None, records=None, rate=22.1):
    now = now or datetime(2026, 11, 11, 22, 30, tzinfo=UTC)
    return asyncio.run(
        manager.async_update(
            records=[{"house": 1.3}] if records is None else records,
            now=now,
            config={"limit": 7.0},
            learned={"soc": 14.0},
            forecast={"name": "tomorrow"},
            forecast_plan={},
            tariff={"price": rate},
        )
    )


def test_live_three_publications_become_one_with_identical_final_payload():
    _, _, Solar = _production_classes()
    original = Solar()
    original._kems_coalesce_live_update_publications = False
    legacy_final = _run(original)

    optimized = Solar()
    optimized_final = _run(optimized)
    assert len(original.published) == 3
    assert len(optimized.published) == 1
    assert optimized_final == legacy_final
    assert optimized.published == [original.published[-1]]
    assert optimized._kems_agile_live_update_coalescing["flow_publication_deferred"]
    assert optimized._kems_agile_live_update_coalescing[
        "canonical_publication_deferred"
    ]
    assert optimized._kems_agile_live_update_coalescing["final_publication_attempted"]
    assert not optimized._kems_agile_live_update_coalescing["fallback_published"]
    assert optimized._kems_defer_flow_live_update_publish is False
    assert optimized._kems_defer_canonical_live_update_publish is False


def test_standalone_flow_and_canonical_owners_keep_immediate_publication():
    Flow, Canonical, _ = _production_classes()
    inner = Flow()
    _run(inner)
    assert len(inner.published) == 1
    independent = Canonical()
    _run(independent)
    assert len(independent.published) == 2


@pytest.mark.parametrize("failure", ["fail_canonical", "fail_solar"])
def test_exception_fallback_restores_last_completed_reporting_stage(failure):
    _, _, Solar = _production_classes()
    legacy = Solar()
    legacy._kems_coalesce_live_update_publications = False
    with pytest.raises(RuntimeError):
        _run(legacy, records=[{failure: True}])

    optimized = Solar()
    with pytest.raises(RuntimeError):
        _run(optimized, records=[{failure: True}])

    assert len(legacy.published) >= 1
    assert len(optimized.published) == 1
    # Every previously published field survives. A partly completed later
    # solar-only enrichment can add diagnostic fields, but must not delete or
    # change the last complete flow, price, or controlled attributes.
    assert all(
        optimized.published[-1].get(key) == value
        for key, value in legacy.published[-1].items()
    )
    assert optimized._kems_agile_live_update_coalescing["fallback_published"]
    assert not optimized._kems_agile_live_update_coalescing[
        "final_publication_attempted"
    ]
    assert optimized._kems_defer_flow_live_update_publish is False
    assert optimized._kems_defer_canonical_live_update_publish is False


def test_each_new_scan_republishes_corrected_tariff_and_midnight_soc():
    _, _, Solar = _production_classes()
    manager = Solar()
    first = _run(manager)
    second = _run(
        manager,
        now=datetime(2026, 11, 12, 0, 0, tzinfo=UTC),
        records=[{"house": 2.2, "settled_correction": True}],
        rate=31.7,
    )
    assert first != second
    assert len(manager.published) == 2
    assert manager.published[0]["simulated_import_rate"] == 22.1
    assert manager.published[1]["simulated_import_rate"] == 31.7
    assert manager.published[1]["records"][0]["settled_correction"] is True
    assert manager.published[1]["solar_elapsed"]["day"] == "2026-11-12"


def test_explicit_disable_preserves_legacy_pass_count_and_stale_flags():
    _, _, Solar = _production_classes()
    manager = Solar()
    manager._kems_coalesce_live_update_publications = False
    manager._kems_defer_flow_live_update_publish = False
    manager._kems_defer_canonical_live_update_publish = False
    _run(manager)
    assert len(manager.published) == 3
    assert manager._kems_agile_live_update_coalescing["enabled"] is False


def test_performance_telemetry_is_read_only_without_hardware_authority():
    coordinator = (ROOT / "coordinator.py").read_text(encoding="utf-8")
    assert '"agile_live_update_publication_coalescing"' in coordinator
    for name in (
        "agile_flow_presentation.py",
        "agile_canonical_flow_accounting.py",
        "agile_live_solar_soc_continuity.py",
    ):
        content = (ROOT / name).read_text(encoding="utf-8")
        assert "_kems_defer_" in content
        assert "self.hass.services.async_call(" not in content
