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
            "sensor.octopus_gas_current_rate",
            "octopus_energy",
            "sensor",
            "octopus gas current rate",
            "gbp/kwh",
            "monetary",
        ),
        candidate(
            "sensor.octopus_gas_current_accumulative_consumption",
            "octopus_energy",
            "sensor",
            "octopus gas current accumulative consumption",
            "kwh",
            "energy",
        ),
        candidate(
            "sensor.octopus_gas_current_accumulative_cost",
            "octopus_energy",
            "sensor",
            "octopus gas current accumulative cost",
            "gbp",
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
    assert result.mappings[constants.CONF_GAS_CURRENT_RATE] == (
        "sensor.octopus_gas_current_rate"
    )
    assert result.mappings[constants.CONF_GAS_USAGE_TODAY] == (
        "sensor.octopus_gas_current_accumulative_consumption"
    )
    assert result.mappings[constants.CONF_GAS_COST_TODAY] == (
        "sensor.octopus_gas_current_accumulative_cost"
    )
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


def test_kyles_octopus_intelligent_and_ohme_inventory_auto_maps() -> None:
    """The observed integration naming patterns should configure in one click."""
    constants, discovery = _load_discovery()
    candidate = discovery.Candidate
    candidates = [
        candidate(
            "sensor.octopus_energy_electricity_meter_current_rate",
            "octopus_energy",
            "sensor",
            "electricity meter current rate electricity",
            "gbp/kwh",
            "monetary",
        ),
        candidate(
            "sensor.octopus_energy_electricity_meter_next_rate",
            "octopus_energy",
            "sensor",
            "electricity meter next rate electricity",
            "gbp/kwh",
            "monetary",
        ),
        candidate(
            "sensor.octopus_energy_electricity_meter_current_standing_charge",
            "octopus_energy",
            "sensor",
            "electricity meter current standing charge electricity",
            "gbp",
            "monetary",
        ),
        candidate(
            "binary_sensor.octopus_energy_electricity_meter_off_peak",
            "octopus_energy",
            "binary_sensor",
            "electricity meter off peak electricity",
            "",
            "",
        ),
        candidate(
            "sensor.octopus_energy_electricity_meter_current_demand",
            "octopus_energy",
            "sensor",
            "electricity meter current demand electricity",
            "w",
            "power",
        ),
        candidate(
            "binary_sensor.octopus_intelligent_tariff_octopus_intelligent_slot",
            "octopus_intelligent",
            "binary_sensor",
            "octopus intelligent tariff octopus intelligent slot",
            "",
            "",
        ),
        candidate(
            "sensor.octopus_intelligent_tariff_octopus_intelligent_next_offpeak_start",
            "octopus_intelligent",
            "sensor",
            "octopus intelligent next offpeak start",
            "",
            "timestamp",
        ),
        candidate(
            "sensor.octopus_intelligent_tariff_octopus_intelligent_offpeak_end",
            "octopus_intelligent",
            "sensor",
            "octopus intelligent offpeak end",
            "",
            "timestamp",
        ),
        candidate(
            "sensor.octopus_energy_gas_meter_current_rate",
            "octopus_energy",
            "sensor",
            "gas meter current rate gas",
            "gbp/kwh",
            "monetary",
        ),
        candidate(
            "sensor.octopus_energy_gas_meter_current_standing_charge",
            "octopus_energy",
            "sensor",
            "gas meter current standing charge gas",
            "gbp",
            "monetary",
        ),
        candidate(
            "sensor.octopus_energy_gas_meter_current_accumulative_consumption_kwh",
            "octopus_energy",
            "sensor",
            "gas meter current accumulative consumption kwh gas",
            "kwh",
            "energy",
        ),
        candidate(
            "sensor.octopus_energy_gas_meter_current_accumulative_cost",
            "octopus_energy",
            "sensor",
            "gas meter current accumulative cost gas",
            "gbp",
            "monetary",
        ),
        candidate(
            "sensor.octopus_energy_gas_meter_current_total_consumption_kwh",
            "octopus_energy",
            "sensor",
            "gas meter current total consumption kwh gas",
            "kwh",
            "energy",
        ),
        candidate(
            "sensor.ohme_epod_status",
            "ohme",
            "sensor",
            "ohme epod status",
            "",
            "enum",
        ),
        candidate(
            "sensor.ohme_epod_power",
            "ohme",
            "sensor",
            "ohme epod power",
            "kw",
            "power",
        ),
        candidate(
            "sensor.ohme_epod_vehicle_battery",
            "ohme",
            "sensor",
            "ohme epod vehicle battery",
            "%",
            "battery",
        ),
    ]

    result = discovery.discover_from_candidates(candidates)

    expected = {
        constants.CONF_CURRENT_IMPORT_RATE,
        constants.CONF_NEXT_IMPORT_RATE,
        constants.CONF_ELECTRICITY_STANDING_CHARGE,
        constants.CONF_OFF_PEAK,
        constants.CONF_INTELLIGENT_SLOT,
        constants.CONF_NEXT_OFFPEAK_START,
        constants.CONF_OFFPEAK_END,
        constants.CONF_GAS_CURRENT_RATE,
        constants.CONF_GAS_STANDING_CHARGE,
        constants.CONF_GAS_USAGE_TODAY,
        constants.CONF_GAS_COST_TODAY,
        constants.CONF_GAS_METER_TOTAL,
        constants.CONF_EV_STATUS,
        constants.CONF_EV_POWER,
        constants.CONF_EV_SOC,
        constants.CONF_HOUSE_LOAD,
        constants.CONF_GRID_IMPORT,
    }
    assert expected <= result.mappings.keys()
    assert result.mappings[constants.CONF_HOUSE_LOAD].endswith("_current_demand")
    assert result.mappings[constants.CONF_GRID_IMPORT].endswith("_current_demand")
    assert result.mappings[constants.CONF_GAS_METER_TOTAL].endswith(
        "_current_total_consumption_kwh"
    )
    assert constants.CONF_GRID_EXPORT not in result.mappings
    assert constants.CONF_CURRENT_EXPORT_RATE not in result.mappings
    assert result.ambiguous == ()


def test_octopus_current_demand_runtime_text_maps_to_grid_import() -> None:
    """The octopus_energy token in the entity ID must not block demand mapping."""
    constants, discovery = _load_discovery()
    entity_id = "sensor.octopus_energy_electricity_meter_current_demand"
    result = discovery.discover_from_candidates(
        [
            discovery.Candidate(
                entity_id,
                "octopus_energy",
                "sensor",
                discovery._normalise(
                    f"{entity_id} Electricity Meter Current Demand Electricity"
                ),
                "w",
                "power",
            )
        ]
    )
    assert result.mappings[constants.CONF_GRID_IMPORT] == entity_id
    assert result.mappings[constants.CONF_HOUSE_LOAD] == entity_id


def test_unsupported_integrations_and_kems_outputs_are_never_discovered() -> None:
    """Only supported provider-owned entities may become KEMS inputs."""
    constants, discovery = _load_discovery()
    candidate = discovery.Candidate
    candidates = [
        candidate(
            "sensor.kems_simulated_grid_export_power",
            "kems",
            "sensor",
            "kems simulated grid export power",
            "kw",
            "power",
        ),
        candidate(
            "sensor.kems_battery_state_of_charge",
            "kems",
            "sensor",
            "kems battery state of charge",
            "%",
            "battery",
        ),
        candidate(
            "binary_sensor.vehicle_battery_plugged",
            "stellantis_vehicles",
            "binary_sensor",
            "vehicle battery plugged",
            "",
            "plug",
        ),
        candidate(
            "binary_sensor.vehicle_battery_charging",
            "stellantis_vehicles",
            "binary_sensor",
            "vehicle battery charging",
            "",
            "battery_charging",
        ),
    ]

    result = discovery.discover_from_candidates(candidates)

    assert constants.CONF_GRID_EXPORT not in result.mappings
    assert constants.CONF_BATTERY_SOC not in result.mappings
    assert constants.CONF_BATTERY_POWER not in result.mappings
    assert constants.CONF_EV_CONNECTED not in result.mappings
    assert constants.CONF_EV_CHARGING not in result.mappings


def test_configured_kems_outputs_and_vehicle_entities_are_rejected() -> None:
    """Validation must remove circular and unrelated configured mappings."""
    constants, discovery = _load_discovery()
    candidate = discovery.Candidate
    kems_export = "sensor.kems_simulated_grid_export_power"
    vehicle_plugged = "binary_sensor.vehicle_battery_plugged"
    validation = discovery.validate_from_candidates(
        {
            constants.CONF_GRID_EXPORT: kems_export,
            constants.CONF_EV_CONNECTED: vehicle_plugged,
        },
        [
            candidate(
                kems_export,
                "kems",
                "sensor",
                "kems simulated grid export power",
                "kw",
                "power",
            ),
            candidate(
                vehicle_plugged,
                "stellantis_vehicles",
                "binary_sensor",
                "vehicle battery plugged",
                "",
                "plug",
            ),
        ],
    )

    assert validation.accepted == {}
    assert set(validation.rejected) == {
        constants.CONF_GRID_EXPORT,
        constants.CONF_EV_CONNECTED,
    }
    assert "cannot be used" in validation.rejected[constants.CONF_GRID_EXPORT]["reason"]
    assert "expected ohme" in validation.rejected[constants.CONF_EV_CONNECTED]["reason"]


def test_daily_gas_accumulator_is_rejected_as_lifetime_meter() -> None:
    """The lifetime gas meter must use total consumption, not today's total."""
    constants, discovery = _load_discovery()
    daily = "sensor.octopus_energy_gas_meter_current_accumulative_consumption_kwh"
    validation = discovery.validate_from_candidates(
        {constants.CONF_GAS_METER_TOTAL: daily},
        [
            discovery.Candidate(
                daily,
                "octopus_energy",
                "sensor",
                "gas meter current accumulative consumption kwh gas",
                "kwh",
                "energy",
            )
        ],
    )

    assert constants.CONF_GAS_METER_TOTAL in validation.rejected
    assert (
        "expected source role"
        in validation.rejected[constants.CONF_GAS_METER_TOTAL]["reason"]
    )


def test_platform_normalisation_preserves_integration_domain() -> None:
    """Platform ownership checks must preserve underscores in HA domains."""
    _, discovery = _load_discovery()

    assert discovery._normalise_platform("octopus_energy") == "octopus_energy"
    assert discovery._normalise_platform("foxess_modbus") == "foxess_modbus"


def test_power_down_sources_are_discovered_with_export_role_separation() -> None:
    """Prefer current Power Down entities and keep import/export baselines apart."""
    constants, discovery = _load_discovery()
    candidates = [
        discovery.Candidate(
            "event.octopus_energy_a_123_octoplus_power_down_events",
            "octopus_energy",
            "event",
            "octopus energy octoplus power down events",
            "",
            "",
        ),
        discovery.Candidate(
            "sensor.octopus_energy_electricity_meter_mpan_octoplus_power_down_baseline",
            "octopus_energy",
            "sensor",
            "octopus energy electricity power down baseline",
            "kwh",
            "energy",
            False,
        ),
        discovery.Candidate(
            (
                "sensor.octopus_energy_electricity_meter_mpan_export_"
                "octoplus_power_down_baseline"
            ),
            "octopus_energy",
            "sensor",
            "octopus energy electricity export power down baseline",
            "kwh",
            "energy",
            True,
        ),
    ]

    result = discovery.discover_from_candidates(candidates)

    assert (
        result.mappings[constants.CONF_SAVING_SESSION_EVENTS] == candidates[0].entity_id
    )
    assert (
        result.mappings[constants.CONF_SAVING_SESSION_IMPORT_BASELINE]
        == candidates[1].entity_id
    )
    assert (
        result.mappings[constants.CONF_SAVING_SESSION_EXPORT_BASELINE]
        == candidates[2].entity_id
    )


def test_legacy_saving_session_event_remains_a_fallback() -> None:
    """Existing accounts can still use the legacy entity until it is removed."""
    constants, discovery = _load_discovery()
    entity_id = "event.octopus_energy_a_123_octoplus_saving_session_events"
    result = discovery.discover_from_candidates(
        [
            discovery.Candidate(
                entity_id,
                "octopus_energy",
                "event",
                "octopus energy octoplus saving session events",
                "",
                "",
            )
        ]
    )
    assert result.mappings[constants.CONF_SAVING_SESSION_EVENTS] == entity_id
