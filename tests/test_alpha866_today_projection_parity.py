"""Regression coverage for Alpha8.66 customer-facing Today projection parity."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _load_slots_module():
    """Load the compatibility publisher without requiring Home Assistant."""
    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.config_entries", config_entries)
    sys.modules.setdefault("homeassistant.core", core)

    name = "alpha866_agile_slots_state"
    spec = importlib.util.spec_from_file_location(name, KEMS / "agile_slots_state.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_customer_slot_aliases_follow_canonical_future_projection() -> None:
    module = _load_slots_module()
    source = {
        "price_quality": {"today_count": 48, "today_expected": 48},
        "today_slots": [
            {
                "label": "19:00",
                "ending_soc_percent": 44.9,
                "grid_export_kwh": 0.0,
                "flow_estimated_soc_percent": 44.9,
                "flow_grid_action": "EXPORT",
                "flow_grid_kwh": 1.656,
                "flow_grid_import_kwh": 0.0,
                "flow_grid_export_kwh": 1.656,
                "flow_battery_export_kwh": 1.656,
                "flow_battery_to_home_kwh": 0.199,
                "flow_scope": "remaining slot",
            },
            {
                "label": "19:30",
                # Reproduces the stale Web.9 fallback seen live: the replay
                # aliases stay at 44.9% / 0.10kWh while canonical flow has
                # already replanned the row to 39.1% / 3.195kWh export.
                "ending_soc_percent": 44.9,
                "grid_export_kwh": 0.098,
                "battery_export_kwh": 0.0,
                "flow_estimated_soc_percent": 39.1,
                "flow_grid_action": "EXPORT",
                "flow_grid_kwh": 3.195,
                "flow_grid_import_kwh": 0.0,
                "flow_grid_export_kwh": 3.195,
                "flow_solar_kwh": 0.098,
                "flow_solar_export_kwh": 0.098,
                "flow_battery_export_kwh": 3.097,
                "flow_battery_to_home_kwh": 0.0,
                "flow_scope": "full slot",
            },
            {
                "label": "20:00",
                "ending_soc_percent": 44.9,
                "grid_export_kwh": 0.0,
                "flow_estimated_soc_percent": 33.3,
                "flow_grid_action": "EXPORT",
                "flow_grid_kwh": 3.097,
                "flow_grid_import_kwh": 0.0,
                "flow_grid_export_kwh": 3.097,
                "flow_battery_export_kwh": 3.097,
                "flow_battery_to_home_kwh": 0.403,
                "flow_scope": "full slot",
            },
        ],
        "tomorrow_slots": [],
        "periods": {},
    }
    original = deepcopy(source)
    coordinator = types.SimpleNamespace(agile_smart_export_state=source)

    attrs = module._attributes(coordinator)
    active, future, later = attrs["today_slots"]

    assert active["ending_soc_percent"] == 44.9
    assert active["grid_export_kwh"] == 1.656
    assert future["ending_soc_percent"] == 39.1
    assert future["grid_export_kwh"] == 3.195
    assert future["battery_export_kwh"] == 3.097
    assert later["ending_soc_percent"] == 33.3
    assert later["grid_export_kwh"] == 3.097
    assert future["presentation_source"] == "canonical flow presentation"
    assert future["presentation_reporting_only"] is True
    assert future["presentation_hardware_writes"] == "blocked"
    assert attrs["presentation_contract"].startswith("canonical flow fields mirrored")

    # This entity is a presentation compatibility boundary only.  The manager
    # state that owns optimiser/dispatch behaviour must remain byte-for-byte
    # equivalent at the Python object level.
    assert source == original


def test_alpha866_is_reporting_only_and_keeps_coordinated_versions() -> None:
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    slots = (KEMS / "agile_slots_state.py").read_text(encoding="utf-8")
    runtime = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")
    alpha864 = (KEMS / "agile_intelligent_dispatch_replan.py").read_text(
        encoding="utf-8"
    )

    assert manifest["version"] == "0.8.0-alpha8.66"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["pi_agent"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["public_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert "presentation_reporting_only" in slots
    assert "presentation_hardware_writes" in slots
    assert "services.async_call" not in slots
    assert "async_call(" not in slots
    assert "IntelligentDispatchObservabilityAgileSmartExportManager" in runtime
    assert "Alpha8.64 keeps the frozen Alpha7 boundary intact" in alpha864
