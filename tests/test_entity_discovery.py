"""Tests for automatic Octopus, Ohme, and FoxESS entity discovery."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "kems"


def _load_discovery() -> tuple[Any, Any]:
    """Load discovery with minimal Home Assistant module stubs."""
    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    helpers = ModuleType("homeassistant.helpers")
    entity_registry = ModuleType("homeassistant.helpers.entity_registry")
    core.HomeAssistant = object

    def async_get(_hass: object) -> None:
        return None

    entity_registry.async_get = async_get
    helpers.entity_registry = entity_registry
    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.entity_registry": entity_registry,
        }
    )

    package_name = "kems_discovery_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    sys.modules[package_name] = package

    loaded = []
    for module_name in ("const", "entity_discovery"):
        qualified_name = f"{package_name}.{module_name}"
        spec = importlib.util.spec_from_file_location(
            qualified_name,
            INTEGRATION / f"{module_name}.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified_name] = module
        spec.loader.exec_module(module)
        loaded.append(module)
    return loaded[0], loaded[1]


def test_supported_entities_are_discovered_without_false_rate_matches() -> None:
    """Current Ohme/FoxESS names should map and tariff types must not cross-map."""
    constants, discovery = _load_discovery()
    candidate = discovery.Candidate
    candidates = [
        candidate(
            "sensor.octopus_current_rate",
            "octopus_energy",
            "sensor",
            "octopus electricity current rate",
            "gbp/kwh",
            "monetary",
        ),
        candidate(
            "sensor.ohme_status",
            "ohme",
            "sensor",
            "ohme charger status",
            "",
            "enum",
        ),
        candidate(
            "sensor.ohme_power",
            "ohme",
            "sensor",
            "ohme charger power",
            "w",
            "power",
        ),
        candidate(
            "sensor.ohme_battery",
            "ohme",
            "sensor",
            "ohme vehicle battery",
            "%",
            "battery",
        ),
        candidate(
            "sensor.foxess_load_power",
            "foxess_modbus",
            "sensor",
            "foxess load power",
            "kw",
            "power",
        ),
        candidate(
            "sensor.foxess_battery_soc",
            "foxess_modbus",
            "sensor",
            "foxess battery soc",
            "%",
            "battery",
        ),
        candidate(
            "sensor.foxess_battery_voltage",
            "foxess_modbus",
            "sensor",
            "foxess battery voltage",
            "v",
            "voltage",
        ),
        candidate(
            "sensor.foxess_battery_current",
            "foxess_modbus",
            "sensor",
            "foxess battery current",
            "a",
            "current",
        ),
        candidate(
            "sensor.foxess_pv_power",
            "foxess_modbus",
            "sensor",
            "foxess pv power",
            "kw",
            "power",
        ),
        candidate(
            "sensor.foxess_grid_consumption",
            "foxess_modbus",
            "sensor",
            "foxess grid consumption",
            "kw",
            "power",
        ),
        candidate(
            "sensor.foxess_feed_in",
            "foxess_modbus",
            "sensor",
            "foxess feed in",
            "kw",
            "power",
        ),
    ]

    result = discovery.discover_from_candidates(candidates)

    assert result.mappings[constants.CONF_CURRENT_IMPORT_RATE] == (
        "sensor.octopus_current_rate"
    )
    assert constants.CONF_NEXT_IMPORT_RATE not in result.mappings
    assert constants.CONF_CURRENT_EXPORT_RATE not in result.mappings
    assert result.mappings[constants.CONF_EV_STATUS] == "sensor.ohme_status"
    assert result.mappings[constants.CONF_EV_POWER] == "sensor.ohme_power"
    assert result.mappings[constants.CONF_EV_SOC] == "sensor.ohme_battery"
    assert result.mappings[constants.CONF_BATTERY_VOLTAGE] == (
        "sensor.foxess_battery_voltage"
    )
    assert result.mappings[constants.CONF_BATTERY_CURRENT] == (
        "sensor.foxess_battery_current"
    )
    assert result.mappings[constants.CONF_GRID_IMPORT] == (
        "sensor.foxess_grid_consumption"
    )
    assert result.mappings[constants.CONF_GRID_EXPORT] == "sensor.foxess_feed_in"
