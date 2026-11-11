"""Read-only live Agile stage timings leave all HA publications untouched.

Execute the three real async_update production methods with deterministic
in-memory reporting dependencies. The _publish stub deliberately mutates state:
KEMS production publishers are NOT pure writers, so no call may be suppressed.
"""

from __future__ import annotations

import ast
import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from textwrap import indent
from time import perf_counter, thread_time
from types import SimpleNamespace

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


class _FakeStates:
    def __init__(self):
        self.current = {}
        self.writes = []

    def get(self, entity_id):
        value = self.current.get(entity_id)
        if value is None:
            return None
        return SimpleNamespace(state=value[0], attributes=value[1])

    def async_set(self, entity_id, value, attributes):
        # HA stores independent state snapshots, not references to mutable slots.
        stored = (str(value), deepcopy(attributes))
        self.current[entity_id] = stored
        self.writes.append((entity_id, *stored))


def _actual_set_mixin():
    """Run the real KEMS _set method against an in-memory HA state machine."""
    source = ast.parse((ROOT / "agile_smart_export.py").read_text("utf-8"))
    cls = next(
        node for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == "AgileSmartExportManager"
    )
    method = next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "_set"
    )
    code = "from __future__ import annotations\nclass RealSet:\n"
    code += indent(ast.unparse(method), "    ") + "\n"
    namespace = {"perf_counter": perf_counter}
    exec(compile(code, "<production-agile-set>", "exec"), namespace)
    return namespace["RealSet"]


class _Base(_actual_set_mixin()):
    def __init__(self):
        self._state = {}
        self.published = []
        self._hass = SimpleNamespace(states=_FakeStates())
        self._alpha850_live_solar_tracker = None
        self._alpha850_live_solar_dirty = False

    @property
    def state(self):
        return deepcopy(self._state)

    def _publish(self, state):
        # A real KEMS _publish also *mutates* rolling/panel/flow state.
        state["publication_enrichment_round"] = len(self.published) + 1
        self.published.append(deepcopy(state))
        self._set(
            "sensor.test_agile_price",
            state["simulated_import_rate"],
            {"unit_of_measurement": "p/kWh"},
        )
        self._set(
            "sensor.test_agile_enrichment_round",
            len(self.published),
            {"source": "live-agile"},
        )

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
        "thread_time": thread_time,
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


def test_three_state_mutating_publications_and_timing_are_retained():
    Flow, Canonical, Solar = _production_classes()
    manager = Solar()
    actual = _run(manager)
    assert len(manager.published) == 3
    assert [entry["publication_enrichment_round"] for entry in manager.published] == [
        1,
        2,
        3,
    ]
    assert actual == manager.published[-1]
    assert actual["publication_enrichment_round"] == 3
    for attribute, key in (
        ("_kems_flow_live_update_performance", "projection_contract_seconds"),
        ("_kems_canonical_live_update_performance", "capture_active_seconds"),
        ("_kems_solar_live_update_performance", "tracker_and_rebase_seconds"),
    ):
        detail = getattr(manager, attribute)
        assert detail["publication_count"] == 1
        assert detail["post_super_seconds"] >= 0
        assert detail["publication_seconds"] >= 0
        assert detail[key] >= 0
        assert detail["post_super_thread_cpu_seconds"] >= 0
    assert "flow_contract" in actual
    assert "active" in actual
    assert "solar_elapsed" in actual
    assert "soc_display" in actual
    assert isinstance(Flow(), Flow)
    assert isinstance(Canonical(), Canonical)


def test_standalone_managers_keep_original_publish_order():
    Flow, Canonical, _Solar = _production_classes()
    manager = Flow()
    _run(manager)
    assert len(manager.published) == 1
    assert manager.published[-1]["publication_enrichment_round"] == 1
    manager = Canonical()
    _run(manager)
    assert len(manager.published) == 2
    assert manager.published[-1]["publication_enrichment_round"] == 2


@pytest.mark.parametrize(
    "failure,expected_passes", [("fail_canonical", 1), ("fail_solar", 2)]
)
def test_failed_overlay_keeps_earlier_synchronous_publications(
    failure, expected_passes
):
    _, _, Solar = _production_classes()
    manager = Solar()
    with pytest.raises(RuntimeError):
        _run(manager, records=[{failure: True}])
    assert len(manager.published) == expected_passes
    assert manager.published[-1]["publication_enrichment_round"] == expected_passes
    assert "flow_contract" in manager.published[-1]


def test_following_scan_recomputes_price_and_midnight_without_cache():
    _, _, Solar = _production_classes()
    manager = Solar()
    _run(manager)
    _run(
        manager,
        now=datetime(2026, 11, 12, 0, 0, tzinfo=UTC),
        records=[{"house": 2.2, "new_settlement": True}],
        rate=33.0,
    )
    assert len(manager.published) == 6
    assert manager.published[-1]["simulated_import_rate"] == 33.0
    assert manager.published[-1]["records"][0]["new_settlement"] is True
    assert manager.published[-1]["solar_elapsed"]["day"] == "2026-11-12"


def test_diagnostics_are_bounded_and_do_not_change_control_or_publication():
    coordinator = (ROOT / "coordinator.py").read_text(encoding="utf-8")
    assert 'f"agile_live_{owner}_{name}"' in coordinator
    assert '"agile_manager_wrapper_seconds"' in coordinator
    for path, owner in (
        ("agile_flow_presentation.py", "FlowPresentationAgileSmartExportManager"),
        (
            "agile_canonical_flow_accounting.py",
            "CanonicalFlowAccountingAgileSmartExportManager",
        ),
        (
            "agile_live_solar_soc_continuity.py",
            "LiveSolarSocContinuityAgileSmartExportManager",
        ),
    ):
        source = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        cls = next(
            item
            for item in source.body
            if isinstance(item, ast.ClassDef) and item.name == owner
        )
        update = next(
            item
            for item in cls.body
            if isinstance(item, ast.AsyncFunctionDef) and item.name == "async_update"
        )
        calls = [
            item
            for item in ast.walk(update)
            if isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "_publish"
        ]
        assert len(calls) == 1
        assert "_kems_defer_flow_live_update_publish" not in ast.unparse(update)
        assert "self.hass.services.async_call(" not in ast.unparse(update)



def test_live_overlay_preserves_all_enrichment_but_suppresses_only_identical_writes():
    """Real _set deduplicates stable values while publishing changed overlays."""
    _, _, Solar = _production_classes()
    manager = Solar()
    first = _run(manager)
    assert first["publication_enrichment_round"] == 3
    assert len(manager.published) == 3
    assert manager._kems_suppress_identical_base_publication is False
    price = [
        entry for entry in manager._hass.states.writes
        if entry[0] == "sensor.test_agile_price"
    ]
    rounds = [
        entry for entry in manager._hass.states.writes
        if entry[0] == "sensor.test_agile_enrichment_round"
    ]
    assert [entry[1] for entry in price] == ["22.1"]
    assert [entry[1] for entry in rounds] == ["1", "2", "3"]

    # New tariff price, new time and changed intermediate overlay must all
    # republish. No cross-scan memoisation, source freezing, or state skipping.
    _run(
        manager,
        now=datetime(2026, 11, 12, 0, 0, tzinfo=UTC),
        rate=37.0,
        records=[{"house": 2.5, "new_receipt": True}],
    )
    assert len(manager.published) == 6
    assert [entry[1] for entry in manager._hass.states.writes
            if entry[0] == "sensor.test_agile_price"] == ["22.1", "37.0"]
    assert [entry[1] for entry in manager._hass.states.writes
            if entry[0] == "sensor.test_agile_enrichment_round"] == [
                "1", "2", "3", "4", "5", "6"
            ]
    assert manager.published[-1]["records"][0]["new_receipt"] is True
    assert manager.published[-1]["solar_elapsed"]["day"] == "2026-11-12"


def test_standalone_direct_publish_keeps_preexisting_repeat_write_semantics():
    """The new suppression is not global and cannot affect other publishers."""
    _, _, Solar = _production_classes()
    manager = Solar()
    _run(manager)
    manager._hass.states.writes.clear()
    manager._publish(manager._state)
    manager._publish(manager._state)
    assert [
        entry[0] for entry in manager._hass.states.writes
        if entry[0] == "sensor.test_agile_price"
    ] == ["sensor.test_agile_price", "sensor.test_agile_price"]
    assert manager._kems_suppress_identical_base_publication is False


def test_live_overlay_failure_restores_original_suppression_flag():
    """An exception in HA publishing must not leak a flag into later scans."""
    _, _, Solar = _production_classes()
    manager = Solar()
    original = manager._publish
    attempts = 0

    def fail_on_canonical(state):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("HA state write failed")
        return original(state)

    manager._publish = fail_on_canonical
    with pytest.raises(RuntimeError, match="HA state write failed"):
        _run(manager)
    assert len(manager.published) == 1
    assert manager._kems_suppress_identical_base_publication is False

    manager._publish = original
    after = _run(manager)
    assert after["publication_enrichment_round"] == 4
    assert manager._kems_suppress_identical_base_publication is False
