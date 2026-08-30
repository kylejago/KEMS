"""Alpha8.60 FoxESS Modbus v1.15 KH commissioning contract tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "kems"


def _load_modules() -> tuple[Any, Any, Any]:
    """Load the contract and discovery code with minimal HA stubs."""
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

    package_name = "kems_alpha860_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    sys.modules[package_name] = package

    loaded = []
    for module_name in ("const", "entity_discovery", "foxess_modbus_contract"):
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
    return loaded[0], loaded[1], loaded[2]


def _fox_candidate(
    discovery: Any,
    entity_id: str,
    original_name: str,
    unit: str,
    device_class: str,
) -> Any:
    """Build metadata matching a foxess_modbus registry candidate."""
    text = discovery._normalise(f"{entity_id} {original_name}")
    return discovery.Candidate(
        entity_id,
        "foxess_modbus",
        "sensor",
        text,
        unit,
        device_class,
    )


def test_v115_kh_contract_is_read_only_and_uses_direct_battery_power() -> None:
    """The reviewed KH contract must prefer invbatpower and block writes."""
    _, _, contract = _load_modules()
    snapshot = contract.foxess_modbus_contract_snapshot()

    assert snapshot["reviewed_upstream_version"] == "1.15.0"
    assert snapshot["kh_families"] == ["KH_PRE119", "KH_PRE133", "KH_133"]
    assert snapshot["required_telemetry"]["battery_soc"]["key"] == "battery_soc"
    assert (
        snapshot["required_telemetry"]["battery_power_kw"]["key"]
        == "invbatpower"
    )
    assert snapshot["battery_power_fallback"]["battery_voltage"]["key"] == (
        "invbatvolt"
    )
    assert snapshot["battery_power_fallback"]["battery_current"]["key"] == (
        "invbatcurrent"
    )
    assert snapshot["writes_permitted"] is False
    assert snapshot["hardware_writes"] == "blocked"


def test_real_v115_kh_inventory_auto_maps_all_required_kems_sources() -> None:
    """Stable upstream KH names should auto-map without ambiguous sources."""
    constants, discovery, contract = _load_modules()
    candidates = [
        _fox_candidate(
            discovery,
            "sensor.kh7_battery_soc",
            "Battery SoC",
            "%",
            "battery",
        ),
        _fox_candidate(
            discovery,
            "sensor.kh7_invbatpower",
            "Inverter Battery Power",
            "kw",
            "power",
        ),
        _fox_candidate(
            discovery,
            "sensor.kh7_pv_power_now",
            "PV Power",
            "kw",
            "power",
        ),
        _fox_candidate(
            discovery,
            "sensor.kh7_load_power",
            "Load Power",
            "kw",
            "power",
        ),
        _fox_candidate(
            discovery,
            "sensor.kh7_grid_consumption",
            "Grid Consumption",
            "kw",
            "power",
        ),
        _fox_candidate(
            discovery,
            "sensor.kh7_feed_in",
            "Feed-in",
            "kw",
            "power",
        ),
    ]

    result = discovery.discover_from_candidates(candidates)
    required = contract.FOXESS_MODBUS_REQUIRED_TELEMETRY

    expected = {
        constants.CONF_BATTERY_SOC: "sensor.kh7_battery_soc",
        constants.CONF_BATTERY_POWER: "sensor.kh7_invbatpower",
        constants.CONF_SOLAR_POWER: "sensor.kh7_pv_power_now",
        constants.CONF_HOUSE_LOAD: "sensor.kh7_load_power",
        constants.CONF_GRID_IMPORT: "sensor.kh7_grid_consumption",
        constants.CONF_GRID_EXPORT: "sensor.kh7_feed_in",
    }
    assert {key: result.mappings[key] for key in expected} == expected
    assert result.ambiguous == ()
    assert {value["key"] for value in required.values()} == {
        "battery_soc",
        "invbatpower",
        "pv_power_now",
        "load_power",
        "grid_consumption",
        "feed_in",
    }


def test_invbat_voltage_current_are_valid_fallback_without_replacing_direct_power() -> None:
    """KH inverter voltage/current may support fallback while power stays primary."""
    constants, discovery, _ = _load_modules()
    candidates = [
        _fox_candidate(
            discovery,
            "sensor.kh7_invbatpower",
            "Inverter Battery Power",
            "kw",
            "power",
        ),
        _fox_candidate(
            discovery,
            "sensor.kh7_invbatvolt",
            "Inverter Battery Voltage",
            "v",
            "voltage",
        ),
        _fox_candidate(
            discovery,
            "sensor.kh7_invbatcurrent",
            "Inverter Battery Current",
            "a",
            "current",
        ),
    ]

    result = discovery.discover_from_candidates(candidates)

    assert result.mappings[constants.CONF_BATTERY_POWER] == "sensor.kh7_invbatpower"
    assert result.mappings[constants.CONF_BATTERY_VOLTAGE] == "sensor.kh7_invbatvolt"
    assert result.mappings[constants.CONF_BATTERY_CURRENT] == (
        "sensor.kh7_invbatcurrent"
    )


def test_raw_grid_and_per_string_pv_do_not_substitute_for_normalised_sources() -> None:
    """Grid CT and PV strings are diagnostics, not KEMS direction/aggregate inputs."""
    constants, discovery, _ = _load_modules()
    candidates = [
        _fox_candidate(discovery, "sensor.kh7_grid_ct", "Grid CT", "kw", "power"),
        _fox_candidate(discovery, "sensor.kh7_pv1_power", "PV1 Power", "kw", "power"),
        _fox_candidate(discovery, "sensor.kh7_pv2_power", "PV2 Power", "kw", "power"),
    ]

    result = discovery.discover_from_candidates(candidates)

    assert constants.CONF_GRID_IMPORT not in result.mappings
    assert constants.CONF_GRID_EXPORT not in result.mappings
    assert constants.CONF_SOLAR_POWER not in result.mappings


def test_known_writable_foxess_capabilities_are_not_kems_input_mappings() -> None:
    """Catalogued FoxESS controls must remain outside the read-only source map."""
    constants, _, contract = _load_modules()
    writable = set(contract.FOXESS_MODBUS_KNOWN_WRITABLE_CAPABILITIES)

    assert writable.isdisjoint(constants.ENTITY_MAPPING_KEYS)
    assert {
        "work_mode",
        "max_charge_current",
        "max_discharge_current",
        "min_soc",
        "max_soc",
        "min_soc_on_grid",
        "export_power_limit",
        "import_power_limit",
    } <= writable
