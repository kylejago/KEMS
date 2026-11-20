"""Retired Intelligent settings and stale KEMS entity registry safety gates."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "kems"


def _cleanup():
    spec = importlib.util.spec_from_file_location(
        "kems_retired_intelligent_cleanup_test", ROOT / "retired_intelligent.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Registry:
    def __init__(self, entities):
        self.entities = dict(entities)
        self.removed = []

    def async_get_entity_id(self, domain, platform, unique_id):
        assert (domain, platform) == ("binary_sensor", "kems")
        for entity_id, value in self.entities.items():
            if value.unique_id == unique_id:
                return entity_id
        return None

    def async_remove(self, entity_id):
        self.removed.append(entity_id)
        del self.entities[entity_id]


class _States:
    def __init__(self, records):
        self.records = records

    def get(self, entity_id):
        value = self.records.get(entity_id)
        return None if value is None else SimpleNamespace(state=value)


def test_retired_option_removed_without_mutating_caller():
    cleanup = _cleanup()
    for stale in (True, False, 1, "true"):
        original = {"intelligent_slots_enabled": stale, "control_enabled": True}
        result = cleanup.without_retired_intelligent_option(original)
        assert result == {"control_enabled": True}
        assert original["intelligent_slots_enabled"] == stale
        assert cleanup.without_retired_intelligent_option(result) == result


def test_registry_cleanup_touches_only_owned_unavailable_orphaned_entities():
    cleanup = _cleanup()
    entity = lambda entry_id, key, platform="kems": SimpleNamespace(
        config_entry_id=entry_id,
        unique_id=f"{entry_id}_{key}",
        platform=platform,
    )
    own_a = "binary_sensor.kems_intelligent_slot"
    own_b = "binary_sensor.kems_intelligent_slot_source_fresh"
    foreign = "binary_sensor.octopus_intelligent_tariff_octopus_intelligent_slot"
    active = "binary_sensor.kems_live_status"
    registry = _Registry(
        {
            own_a: entity("entry-1", "intelligent_slot"),
            own_b: entity("entry-1", "intelligent_slot_source_fresh"),
            foreign: entity("entry-2", "intelligent_slot", "octopus_intelligent"),
            active: entity("entry-1", "live_status"),
        }
    )
    states = _States(
        {own_a: "unavailable", own_b: "unknown", foreign: "off", active: "on"}
    )
    removed = cleanup.retire_unavailable_kems_intelligent_entities(
        registry, states, entry_id="entry-1"
    )
    assert removed == (own_a, own_b)
    assert set(registry.entities) == {foreign, active}
    assert cleanup.retire_unavailable_kems_intelligent_entities(
        registry, states, entry_id="entry-1"
    ) == ()


def test_registry_cleanup_never_removes_live_or_other_entry_sensor():
    cleanup = _cleanup()
    own = "binary_sensor.kems_intelligent_slot"
    candidate = SimpleNamespace(
        config_entry_id="entry-1",
        unique_id="entry-1_intelligent_slot",
        platform="kems",
    )
    registry = _Registry({own: candidate})
    assert cleanup.retire_unavailable_kems_intelligent_entities(
        registry, _States({own: "on"}), entry_id="entry-1"
    ) == ()
    assert registry.removed == []
    candidate.config_entry_id = "other-entry"
    assert cleanup.retire_unavailable_kems_intelligent_entities(
        registry, _States({own: "unavailable"}), entry_id="entry-1"
    ) == ()
    assert registry.removed == []


def test_all_options_write_surfaces_strip_retired_key():
    setup = (ROOT / "__init__.py").read_text()
    runtime = (ROOT / "runtime_options.py").read_text()
    flow = (ROOT / "config_flow.py").read_text()
    binary = (ROOT / "binary_sensor.py").read_text()
    assert "options = without_retired_intelligent_option(options)" in setup
    assert "retire_unavailable_kems_intelligent_entities(" in setup
    assert "without_retired_intelligent_option(" in runtime
    assert runtime.count("without_retired_intelligent_option(") >= 4
    assert "options=without_retired_intelligent_option(self._initial_options)" in flow
    assert "data=without_retired_intelligent_option(options)" in flow
    binary_ast = ast.parse(binary)
    assert not any(
        isinstance(node, ast.keyword)
        and node.arg == "key"
        and isinstance(node.value, ast.Constant)
        and node.value.value in {"intelligent_slot", "intelligent_slot_source_fresh"}
        for node in ast.walk(binary_ast)
    )
