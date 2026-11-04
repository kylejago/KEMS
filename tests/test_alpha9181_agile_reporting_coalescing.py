"""Alpha9.181: suppress only the guaranteed redundant canonical publication.

Run the actual Canonical and Deadline methods against the unchanged synchronous
layer ordering. Flow still publishes first, preserving SOC/price visibility;
Solar and deadline changes reach HA together in the final publication.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import pytest

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"
NOW = datetime(2026, 11, 4, 14, 5, tzinfo=UTC)


def _method(filename, owner):
    source = ast.parse((KEMS / filename).read_text(encoding="utf-8"))
    cls = next(
        x for x in source.body if isinstance(x, ast.ClassDef) and x.name == owner
    )
    return next(
        x
        for x in cls.body
        if isinstance(x, ast.FunctionDef)
        and x.name == "reconcile_current_day_settlements"
    )


def _owners():
    class SimulationConfig:
        pass

    class Recorder:
        def __init__(self):
            self.events = []
            self._state = {}
            self._rolling_config = SimulationConfig()
            self._alpha849_live_replay_capture = {"source": "saved capture"}
            self._kems_settlement_publication_scope = {
                "deferred_canonical_flow_publications": 0
            }
            self.fail_early = False
            self.fail_solar = False

        @property
        def state(self):
            return dict(self._state)

        def reconcile_current_day_settlements(self, *, settled_half_hours, now):
            if self.fail_early:
                raise RuntimeError("early failure")
            self._state.update(
                {
                    "settled_soc": 61.2,
                    "price_pence": 26.7,
                    "period": "completed first",
                }
            )
            self._publish(self._state)
            return self.state

        def _publish(self, state):
            # Collect the exact state present at publication (no delayed async).
            self.events.append(("publish", dict(state)))

    class Flow(Recorder):
        def reconcile_current_day_settlements(self, *, settled_half_hours, now):
            super().reconcile_current_day_settlements(
                settled_half_hours=settled_half_hours, now=now
            )
            self._state["flow"] = "settled"
            self._publish(self._state)
            return self.state

    def apply_captured(state, *, now, capture):
        assert capture["source"] == "saved capture"
        state["solar_income"] = 11.9

    def active_route(state, *, now, config):
        state["active_route_soc"] = 61.2

    class SolarStub:
        # Replaced with a class inheriting Canonical.
        pass

    namespace = {
        "__name__": __name__,
        "Recorder": Recorder,
        "Flow": Flow,
        "SimulationConfig": SimulationConfig,
        "_apply_captured_live_solar_accounting": apply_captured,
        "_active_slot_from_routing": active_route,
        "perf_counter": perf_counter,
    }
    canonical = ast.ClassDef(
        name="Canonical",
        bases=[ast.Name(id="Flow", ctx=ast.Load())],
        keywords=[],
        body=[
            _method(
                "agile_canonical_flow_accounting.py",
                "CanonicalFlowAccountingAgileSmartExportManager",
            )
        ],
        decorator_list=[],
    )
    program = ast.Module(body=[canonical], type_ignores=[])
    exec(compile(ast.fix_missing_locations(program), "<canonical>", "exec"), namespace)
    Canonical = namespace["Canonical"]

    class Solar(Canonical):
        def reconcile_current_day_settlements(self, *, settled_half_hours, now):
            super().reconcile_current_day_settlements(
                settled_half_hours=settled_half_hours, now=now
            )
            if self.fail_solar:
                raise RuntimeError("solar failure")
            self._state["solar"] = "elapsed reconciled"
            if not getattr(self, "_kems_defer_solar_settlement_publish", False):
                self._publish(self._state)
            return self.state

    def deadline_rebase(state, *, config):
        assert state["flow"] == "settled"
        assert state["active_route_soc"] == 61.2
        assert state["solar_income"] == 11.9
        assert state["solar"] == "elapsed reconciled"
        state["deadline_soc"] = state["settled_soc"]
        return {"applied": True}

    namespace.update(
        {
            "Solar": Solar,
            "rebase_day_summary_deadline_from_rolling": deadline_rebase,
        }
    )
    deadline = ast.ClassDef(
        name="Deadline",
        bases=[ast.Name(id="Solar", ctx=ast.Load())],
        keywords=[],
        body=[
            _method(
                "agile_deadline_settlement_consistency.py",
                "DeadlineSettlementConsistencyAgileSmartExportManager",
            )
        ],
        decorator_list=[],
    )
    program = ast.Module(body=[deadline], type_ignores=[])
    exec(compile(ast.fix_missing_locations(program), "<deadline>", "exec"), namespace)
    return Canonical, Solar, namespace["Deadline"]


def test_deadline_coalesces_one_canonical_pass_without_losing_settled_payload():
    _, _, Deadline = _owners()
    owner = Deadline()
    result = owner.reconcile_current_day_settlements(
        settled_half_hours=[{"settled": True}], now=NOW
    )
    # Mandatory settled publication, followed by Flow publication, followed
    # by the combined Solar+Canonical+Deadline final publish.
    assert len(owner.events) == 3
    assert "solar_income" not in owner.events[1][1]
    assert result["active_route_soc"] == 61.2
    assert result["deadline_soc"] == 61.2
    assert owner.events[-1][1]["price_pence"] == 26.7
    assert owner.events[-1][1]["solar_income"] == 11.9
    assert owner.events[-1][1]["deadline_soc"] == 61.2
    assert owner._kems_settlement_publication_scope[
        "deferred_canonical_flow_publications"
    ] == 1
    assert owner._kems_defer_canonical_settlement_publish is False
    assert owner._kems_defer_solar_settlement_publish is False


def test_direct_canonical_and_solar_callers_retain_original_publications():
    Canonical, Solar, _ = _owners()
    direct = Canonical()
    direct.reconcile_current_day_settlements(settled_half_hours=[], now=NOW)
    assert len(direct.events) == 3
    assert direct.events[-1][1]["solar_income"] == 11.9
    assert direct._kems_settlement_publication_scope[
        "deferred_canonical_flow_publications"
    ] == 0

    solar = Solar()
    solar.reconcile_current_day_settlements(settled_half_hours=[], now=NOW)
    assert len(solar.events) == 4
    assert solar.events[-1][1]["solar"] == "elapsed reconciled"


@pytest.mark.parametrize("cause", ["early", "solar"])
def test_exception_cleans_defer_flags_without_delayed_or_control_writes(cause):
    _, _, Deadline = _owners()
    owner = Deadline()
    owner.fail_early = cause == "early"
    owner.fail_solar = cause == "solar"
    with pytest.raises(RuntimeError):
        owner.reconcile_current_day_settlements(settled_half_hours=[], now=NOW)
    assert owner._kems_defer_canonical_settlement_publish is False
    assert owner._kems_defer_solar_settlement_publish is False
    assert all(kind == "publish" for kind, _ in owner.events)


def test_coalescing_has_no_change_to_precontrol_first_publication_or_fast_control():
    coordinator = (KEMS / "coordinator.py").read_text()
    assert "with coalesce_identical_settlement_publications(" in coordinator
    assert "pre_settlement = (" in coordinator
    assert "pre_settlement.get(\"current_day_settlement_reconciliation\", {})" in coordinator
    deadline = (KEMS / "agile_deadline_settlement_consistency.py").read_text()
    assert "self._publish(self._state)" in deadline
    assert "finally:" in deadline
    canonical = (KEMS / "agile_canonical_flow_accounting.py").read_text()
    assert "if not getattr(" in canonical
    assert "self._publish(self._state)" in canonical
