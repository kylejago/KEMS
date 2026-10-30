"""Alpha9.161: suppress identical settlement writes without stale reporting."""

from __future__ import annotations

import ast
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

from kems_core.settlement_publication_coalescing import (
    coalesce_identical_settlement_publications,
)

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"


def _isolated_setter():
    module = ast.parse((KEMS / "agile_smart_export.py").read_text())
    owner = next(
        n
        for n in module.body
        if isinstance(n, ast.ClassDef) and n.name == "AgileSmartExportManager"
    )
    method = next(
        n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == "_set"
    )
    isolated = ast.ClassDef(
        name="Setter", bases=[], keywords=[], body=[method], decorator_list=[]
    )
    namespace = {"perf_counter": perf_counter, "Any": Any}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[isolated], type_ignores=[])),
            "<settlement-setter>",
            "exec",
        ),
        namespace,
    )
    return namespace["Setter"]


class States:
    def __init__(self):
        self.values = {}
        self.calls = []

    def async_set(self, entity_id, value, attributes):
        self.calls.append((entity_id, value, attributes))
        self.values[entity_id] = SimpleNamespace(
            state=value, attributes=dict(attributes)
        )

    def get(self, entity_id):
        return self.values.get(entity_id)


def _manager():
    manager = _isolated_setter()()
    manager._hass = SimpleNamespace(states=States())
    return manager


def test_exact_repeated_writes_skipped_but_changes_not_skipped() -> None:
    m = _manager()
    with coalesce_identical_settlement_publications(m) as scope:
        m._set("sensor.agile_plan", "Ready", {"slots": [1, 2]})
        m._set("sensor.agile_plan", "Ready", {"slots": [1, 2]})
        m._set("sensor.agile_plan", "Ready", {"slots": [1, 3]})
        m._set("sensor.agile_plan", "Ready", {"slots": [1, 3]})
        m._set("sensor.agile_cost", 10, {"price": 10})
    assert len(m._hass.states.calls) == 3
    assert scope.summary()["skipped_identical"] == 2
    assert m._hass.states.get("sensor.agile_plan").attributes["slots"] == [1, 3]
    assert m._kems_settlement_publication_scope is None


def test_new_soc_and_tariff_changes_publish_in_same_pass() -> None:
    m = _manager()
    with coalesce_identical_settlement_publications(m) as scope:
        for soc in (70, 70, 71, 71):
            m._set("sensor.tomorrow_handoff", soc, {"soc": soc})
        m._set("sensor.tomorrow_prices", 18.0, {"rate": 18.0})
        m._set("sensor.tomorrow_prices", 19.6, {"rate": 19.6})
    assert scope.summary()["written"] == 4
    assert [row[1] for row in m._hass.states.calls[:2]] == ["70", "71"]
    assert m._hass.states.get("sensor.tomorrow_prices").state == "19.6"


def test_second_pass_does_not_inherit_first_pass_seen_set() -> None:
    m = _manager()
    with coalesce_identical_settlement_publications(m):
        m._set("sensor.a", "first", {})
        m._set("sensor.a", "first", {})
    with coalesce_identical_settlement_publications(m) as scope:
        m._set("sensor.a", "first", {})
    assert scope.summary()["written"] == 1
    assert len(m._hass.states.calls) == 2


def test_exception_resets_scope_and_no_writes_are_delayed() -> None:
    m = _manager()
    try:
        with coalesce_identical_settlement_publications(m):
            m._set("sensor.a", "first", {})
            raise RuntimeError("Injected reporting exception")
    except RuntimeError:
        pass
    assert m._kems_settlement_publication_scope is None
    m._set("sensor.a", "second", {})
    assert [row[1] for row in m._hass.states.calls] == ["first", "second"]


def test_control_and_settlement_phases_preserved() -> None:
    source = (KEMS / "coordinator.py").read_text()
    before = source.index("settled_before_shadow = settled_half_hour_snapshot(")
    first = source.index('detail_seconds["precontrol_settlement_reconciliation"]')
    control = source.index("control = self._control.plan(")
    shadow = source.index("await self._shadow_validation.async_update(")
    second = source.index("if post_shadow_settlement_changed:")
    writer = source.index("foxess_control = await self._foxess_control.async_update(")
    assert before < first < control < shadow < second < writer
    assert source.count("with coalesce_identical_settlement_publications(") == 2
    assert '"settlement_publication_coalescing": settlement_publication_stats' in source
