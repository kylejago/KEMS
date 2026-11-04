"""Alpha9.179: restart attribution and publication timing are observation-only."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from kems_core.settlement_publication_coalescing import (
    coalesce_identical_settlement_publications,
)

KEMS = Path(__file__).parents[1] / "custom_components" / "kems"
spec = importlib.util.spec_from_file_location(
    "kems_restart_request_observability", KEMS / "restart_request_observability.py"
)
assert spec is not None and spec.loader is not None
restart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restart)
classify = restart.classify_restart_service_call


def test_explicit_restart_call_is_classified_without_user_identity():
    event = SimpleNamespace(
        data={
            "domain": "homeassistant",
            "service": "restart",
            "service_data": {"confirmation": "private"},
        },
        context=SimpleNamespace(user_id="sensitive-user-id", parent_id="opaque-parent"),
    )
    result = classify(event, now=datetime(2026, 11, 4, 9, 44, tzinfo=UTC))
    assert result["status"] == "restart_service_called"
    assert result["user_context_present"] is True
    assert result["parent_context_present"] is True
    assert result["hardware_writes"] == "none"
    assert "sensitive-user-id" not in str(result)
    assert "opaque-parent" not in str(result)
    assert "private" not in str(result)


def test_other_service_and_missing_context_are_safe():
    now = datetime(2026, 11, 4, tzinfo=UTC)
    assert (
        classify(
            SimpleNamespace(data={"domain": "light", "service": "turn_on"}), now=now
        )
        is None
    )
    assert classify(SimpleNamespace(data={}), now=now) is None
    assert classify(SimpleNamespace(data="bad"), now=now) is None
    result = classify(
        SimpleNamespace(data={"domain": "homeassistant", "service": "restart"}),
        now=now,
    )
    assert result["user_context_present"] is False
    assert result["parent_context_present"] is False


def test_settlement_layer_timing_is_bounded_to_one_existing_scope():
    manager = SimpleNamespace()
    with coalesce_identical_settlement_publications(manager) as scope:
        scope.record_layer("restart_soc_anchor_prepublication", 0.125)
        scope.record_layer("restart_soc_anchor_prepublication", 0.125)
        scope.record_layer("underlying_agile_publication_chain", 0.5)
        assert scope.summary()["layer_seconds"] == {
            "restart_soc_anchor_prepublication": 0.25,
            "underlying_agile_publication_chain": 0.5,
        }
        assert scope.summary()["layer_calls"] == {
            "restart_soc_anchor_prepublication": 2,
            "underlying_agile_publication_chain": 1,
        }
    assert manager._kems_settlement_publication_scope is None
    with coalesce_identical_settlement_publications(manager) as later:
        assert later.summary()["layer_seconds"] == {}
        assert later.summary()["written"] == 0


def test_no_control_authority_or_restart_action_is_added():
    coordinator = (KEMS / "coordinator.py").read_text(encoding="utf-8")
    anchor = (KEMS / "agile_restart_soc_anchor.py").read_text(encoding="utf-8")
    assert (
        'hass.bus.async_listen("call_service", self._handle_restart_service_call)'
        in coordinator
    )
    assert "entry.async_on_unload(" in coordinator
    assert 'evidence["user_context_present"]' in coordinator
    assert "scope.record_layer(" in anchor
    assert (
        "IntelligentDispatchObservabilityAgileSmartExportManager._publish(self, state)"
        in anchor
    )
    assert "self._foxess_control.async_update(" in coordinator
