"""Alpha9.82 regression coverage for continuous Today -> Tomorrow SOC flow."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
LONDON = ZoneInfo("Europe/London")


def _load_handoff():
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientError = type("ClientError", (Exception,), {})
    sys.modules.setdefault("aiohttp", aiohttp)

    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        def __class_getitem__(cls, item):
            return cls

    storage.Store = Store
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.core", core)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)
    sys.modules.setdefault("homeassistant.helpers.storage", storage)

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = types.ModuleType("custom_components.kems")
    package.__path__ = [str(INTEGRATION)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.kems", package)

    agile_name = "custom_components.kems.agile_smart_export"
    spec = importlib.util.spec_from_file_location(
        agile_name,
        INTEGRATION / "agile_smart_export.py",
    )
    assert spec is not None and spec.loader is not None
    agile = importlib.util.module_from_spec(spec)
    sys.modules[agile_name] = agile
    spec.loader.exec_module(agile)
    return importlib.import_module("custom_components.kems.agile_settled_soc_handoff")


def test_today_final_display_soc_is_exact_tomorrow_boundary_authority() -> None:
    handoff = _load_handoff()
    state = {
        "today_slots": [
            {
                "valid_from": "2026-10-06T22:30:00+00:00",
                "valid_to": "2026-10-06T23:00:00+00:00",
                "flow_estimated_soc_percent": 20.9,
                "ending_soc_percent": 77.4,
            }
        ]
    }

    result = handoff._today_display_midnight_soc(
        state,
        now=datetime(2026, 10, 6, 22, 51, tzinfo=LONDON),
    )

    assert result == (20.9, "flow_estimated_soc_percent")


def test_raw_replay_soc_is_only_fallback_when_flow_soc_missing() -> None:
    handoff = _load_handoff()
    state = {
        "today_slots": [
            {
                "valid_from": "2026-10-06T22:30:00+00:00",
                "valid_to": "2026-10-06T23:00:00+00:00",
                "ending_soc_percent": 20.9,
            }
        ]
    }

    assert handoff._today_display_midnight_soc(
        state,
        now=datetime(2026, 10, 6, 22, 51, tzinfo=LONDON),
    ) == (20.9, "ending_soc_percent")


def test_non_midnight_slot_cannot_seed_tomorrow() -> None:
    handoff = _load_handoff()
    state = {
        "today_slots": [
            {
                "valid_from": "2026-10-06T22:00:00+00:00",
                "valid_to": "2026-10-06T22:30:00+00:00",
                "flow_estimated_soc_percent": 20.9,
            }
        ]
    }

    assert handoff._today_display_midnight_soc(
        state,
        now=datetime(2026, 10, 6, 22, 51, tzinfo=LONDON),
    ) is None


def test_settlement_flow_refreshes_routing_before_flow_contract() -> None:
    source = (INTEGRATION / "agile_flow_presentation.py").read_text()
    reconcile = source[source.index("def reconcile_current_day_settlements"):]

    enrich = reconcile.index("_enrich_slot_routing(")
    attach = reconcile.index("_attach_flow_contract(")
    publish = reconcile.index("self._publish(self._state)")

    assert enrich < attach < publish
    assert "tomorrow_slots" in reconcile
    assert "hardware writes" not in reconcile.lower()


def test_midnight_handoff_remains_reporting_only() -> None:
    source = (INTEGRATION / "agile_settled_soc_handoff.py").read_text()

    assert "_today_display_midnight_soc" in source
    assert "today_to_tomorrow_continuity_applied" in source
    assert '"hardware_writes": "blocked"' in source
    assert ".services.async_call(" not in source
    assert "safe_to_write_hardware = True" not in source
