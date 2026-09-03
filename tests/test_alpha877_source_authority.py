"""Alpha8.77 regression tests for deterministic commissioning source authority."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "kems"


def _load_source_authority() -> tuple[Any, Any]:
    """Load source authority with minimal Home Assistant module stubs."""
    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    helpers = ModuleType("homeassistant.helpers")
    entity_registry = ModuleType("homeassistant.helpers.entity_registry")
    core.HomeAssistant = object
    entity_registry.async_get = lambda _hass: None
    helpers.entity_registry = entity_registry
    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.core": core,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.entity_registry": entity_registry,
        }
    )

    package_name = "kems_source_authority_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    sys.modules[package_name] = package

    loaded: dict[str, Any] = {}
    for module_name in ("const", "entity_discovery", "source_authority"):
        qualified_name = f"{package_name}.{module_name}"
        spec = importlib.util.spec_from_file_location(
            qualified_name,
            INTEGRATION / f"{module_name}.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified_name] = module
        spec.loader.exec_module(module)
        loaded[module_name] = module
    return loaded["const"], loaded["source_authority"]


def test_valid_same_platform_source_is_stable_across_discovery() -> None:
    """Discovery must not silently replace one valid source with a peer."""
    constants, authority = _load_source_authority()
    accepted = {
        constants.CONF_CURRENT_IMPORT_RATE: "sensor.octopus_rate_explicit",
    }
    discovered = {
        constants.CONF_CURRENT_IMPORT_RATE: "sensor.octopus_rate_other",
    }
    platforms = {
        "sensor.octopus_rate_explicit": "octopus_energy",
        "sensor.octopus_rate_other": "octopus_energy",
    }

    result = authority.reconcile_source_mappings(accepted, discovered, platforms)

    assert result.mappings == accepted
    assert result.upgrades == {}


def test_preinstall_octopus_fallback_promotes_to_foxess_physical_truth() -> None:
    """House/grid fallback should promote once higher-priority FoxESS data exists."""
    constants, authority = _load_source_authority()
    fallback = "sensor.octopus_energy_electricity_meter_current_demand"
    accepted = {
        constants.CONF_HOUSE_LOAD: fallback,
        constants.CONF_GRID_IMPORT: fallback,
    }
    discovered = {
        constants.CONF_HOUSE_LOAD: "sensor.foxess_load_power",
        constants.CONF_GRID_IMPORT: "sensor.foxess_grid_consumption",
        constants.CONF_GRID_EXPORT: "sensor.foxess_feed_in",
    }
    platforms = {
        fallback: "octopus_energy",
        "sensor.foxess_load_power": "foxess_modbus",
        "sensor.foxess_grid_consumption": "foxess_modbus",
        "sensor.foxess_feed_in": "foxess_modbus",
    }

    result = authority.reconcile_source_mappings(accepted, discovered, platforms)

    assert result.mappings[constants.CONF_HOUSE_LOAD] == "sensor.foxess_load_power"
    assert result.mappings[constants.CONF_GRID_IMPORT] == (
        "sensor.foxess_grid_consumption"
    )
    assert result.mappings[constants.CONF_GRID_EXPORT] == "sensor.foxess_feed_in"
    assert set(result.upgrades) == {
        constants.CONF_HOUSE_LOAD,
        constants.CONF_GRID_IMPORT,
    }


def test_lower_priority_discovery_cannot_replace_foxess_truth() -> None:
    """A later fallback discovery must never demote a commissioned source."""
    constants, authority = _load_source_authority()
    accepted = {
        constants.CONF_HOUSE_LOAD: "sensor.foxess_load_power",
        constants.CONF_GRID_IMPORT: "sensor.foxess_grid_consumption",
    }
    fallback = "sensor.octopus_energy_electricity_meter_current_demand"
    discovered = {
        constants.CONF_HOUSE_LOAD: fallback,
        constants.CONF_GRID_IMPORT: fallback,
    }
    platforms = {
        "sensor.foxess_load_power": "foxess_modbus",
        "sensor.foxess_grid_consumption": "foxess_modbus",
        fallback: "octopus_energy",
    }

    result = authority.reconcile_source_mappings(accepted, discovered, platforms)

    assert result.mappings == accepted
    assert result.upgrades == {}


def test_physical_source_aliases_are_explicit_commissioning_evidence() -> None:
    """Shared physical telemetry must be detectable without banning fallback use."""
    constants, authority = _load_source_authority()
    fallback = "sensor.octopus_energy_electricity_meter_current_demand"
    mappings = {
        constants.CONF_HOUSE_LOAD: fallback,
        constants.CONF_GRID_IMPORT: fallback,
        constants.CONF_BATTERY_SOC: "sensor.foxess_battery_soc",
    }

    duplicates = authority.duplicate_physical_sources(mappings)

    assert duplicates == {
        fallback: tuple(
            sorted((constants.CONF_GRID_IMPORT, constants.CONF_HOUSE_LOAD))
        )
    }


def test_distinct_foxess_contract_has_no_physical_source_aliases() -> None:
    """The reviewed commissioning telemetry contract has one entity per role."""
    constants, authority = _load_source_authority()
    mappings = {
        constants.CONF_HOUSE_LOAD: "sensor.foxess_load_power",
        constants.CONF_BATTERY_SOC: "sensor.foxess_battery_soc",
        constants.CONF_BATTERY_POWER: "sensor.foxess_invbatpower",
        constants.CONF_BATTERY_VOLTAGE: "sensor.foxess_invbatvolt",
        constants.CONF_BATTERY_CURRENT: "sensor.foxess_invbatcurrent",
        constants.CONF_SOLAR_POWER: "sensor.foxess_pv_power_now",
        constants.CONF_GRID_IMPORT: "sensor.foxess_grid_consumption",
        constants.CONF_GRID_EXPORT: "sensor.foxess_feed_in",
    }

    assert authority.duplicate_physical_sources(mappings) == {}
