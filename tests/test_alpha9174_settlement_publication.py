"""Alpha9.174 publication-order regression for the synchronous settled-day chain."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


def _load_reconciliation_layers():
    """Exercise the real methods with HA-independent dependency stubs."""

    class SimulationConfig:
        pass

    class FakeBase:
        def __init__(self):
            self._state = {}
            self._alpha850_live_solar_tracker = {"sample_count": 1}
            self._rolling_config = SimulationConfig()
            self.events = []
            self.fail_reconcile = False

        @property
        def state(self):
            return dict(self._state)

        def reconcile_current_day_settlements(self, *, settled_half_hours, now):
            self.events.append("settled_base")
            if self.fail_reconcile:
                raise RuntimeError("injected settlement failure")
            self._state["base_settled"] = True
            return self.state

        def _publish(self, state):
            self.events.append("publish")
            assert state["base_settled"]
            assert state["solar_settled"]
            assert state["display_soc_rebased"]

    def solar_accounting(state, *, tracker, now):
        assert tracker["sample_count"] == 1
        state["solar_settled"] = True

    def display_soc(state, *, now, config):
        assert state["solar_settled"]
        state["display_soc_rebased"] = True

    def deadline_rebase(state, *, config):
        assert state["display_soc_rebased"]
        state["deadline_rebased"] = True
        return {"applied": True}

    def extract_method(filename, classname):
        module = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
        owner = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name == classname
        )
        return next(
            node
            for node in owner.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "reconcile_current_day_settlements"
        )

    solar_method = extract_method(
        "agile_live_solar_soc_continuity.py",
        "LiveSolarSocContinuityAgileSmartExportManager",
    )
    deadline_method = extract_method(
        "agile_deadline_settlement_consistency.py",
        "DeadlineSettlementConsistencyAgileSmartExportManager",
    )
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            ast.ClassDef(
                name="Solar",
                bases=[ast.Name(id="FakeBase", ctx=ast.Load())],
                keywords=[],
                body=[solar_method],
                decorator_list=[],
            ),
            ast.ClassDef(
                name="Deadline",
                bases=[ast.Name(id="Solar", ctx=ast.Load())],
                keywords=[],
                body=[deadline_method],
                decorator_list=[],
            ),
        ],
        type_ignores=[],
    )
    namespace = {
        "__name__": __name__,
        "FakeBase": FakeBase,
        "SimulationConfig": SimulationConfig,
        "_apply_elapsed_solar_accounting": solar_accounting,
        "_rebase_display_soc": display_soc,
        "rebase_day_summary_deadline_from_rolling": deadline_rebase,
    }
    exec(compile(ast.fix_missing_locations(module), str(ROOT), "exec"), namespace)
    return namespace["Solar"], namespace["Deadline"]


def test_direct_solar_reconciliation_still_publishes_synchronously() -> None:
    Solar, _ = _load_reconciliation_layers()
    owner = Solar()
    result = owner.reconcile_current_day_settlements(
        settled_half_hours=[], now=datetime(2026, 11, 3, tzinfo=UTC)
    )
    assert owner.events == ["settled_base", "publish"]
    assert result["display_soc_rebased"]
    assert not result.get("deadline_rebased")


def test_deadline_owner_coalesces_solar_publication_without_losing_fields() -> None:
    _, Deadline = _load_reconciliation_layers()
    owner = Deadline()

    def final_publish(state):
        assert state == {
            "base_settled": True,
            "solar_settled": True,
            "display_soc_rebased": True,
            "deadline_rebased": True,
        }
        owner.events.append("final_publish")

    owner._publish = final_publish
    result = owner.reconcile_current_day_settlements(
        settled_half_hours=[], now=datetime(2026, 11, 3, tzinfo=UTC)
    )
    assert owner.events == ["settled_base", "final_publish"]
    assert result["deadline_rebased"]
    assert owner._kems_defer_solar_settlement_publish is False


def test_deadline_defer_flag_is_restored_after_settlement_failure() -> None:
    import pytest

    _, Deadline = _load_reconciliation_layers()
    owner = Deadline()
    owner.fail_reconcile = True
    with pytest.raises(RuntimeError, match="injected settlement failure"):
        owner.reconcile_current_day_settlements(
            settled_half_hours=[], now=datetime(2026, 11, 3, tzinfo=UTC)
        )
    assert owner._kems_defer_solar_settlement_publish is False
    assert "publish" not in owner.events
