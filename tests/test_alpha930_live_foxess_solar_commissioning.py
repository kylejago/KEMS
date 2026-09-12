"""Alpha9.30 regression contract for live FoxESS solar-only commissioning."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from kems_core.commissioning_evidence import (
    assess_foxess_power_balance,
    assess_foxess_telemetry_stability,
    assess_foxess_unit_contract,
)

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
MANIFEST = INTEGRATION / "manifest.json"
PANEL = INTEGRATION / "panel.py"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"
COMMISSIONING = INTEGRATION / "commissioning.py"


def _load_discovery() -> tuple[Any, Any]:
    """Load discovery with minimal Home Assistant module stubs."""
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

    package_name = "kems_alpha930_discovery_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    sys.modules[package_name] = package

    loaded: dict[str, Any] = {}
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
        loaded[module_name] = module
    return loaded["const"], loaded["entity_discovery"]


def _record(timestamp: datetime) -> SimpleNamespace:
    """Return one no-battery physical site observation."""
    return SimpleNamespace(
        timestamp=timestamp,
        stale_fields=("battery_soc", "battery_power_kw"),
        battery_soc=None,
        battery_power_kw=None,
        solar_power_kw=2.0,
        house_load_kw=0.75,
        grid_import_kw=0.0,
        grid_export_kw=1.25,
    )


def test_real_kh_entity_ids_win_over_preinstall_fallback_and_aggregate_variants() -> None:
    """Live KH power entities should be discovered without aggregate ambiguity."""
    constants, discovery = _load_discovery()
    candidate = discovery.Candidate
    candidates = [
        candidate(
            "sensor.kh7_load_power",
            "foxess_modbus",
            "sensor",
            "foxess modbus kh7 load power kh7",
            "kw",
            "power",
        ),
        candidate(
            "sensor.kh7_load_power_total",
            "foxess_modbus",
            "sensor",
            "foxess modbus kh7 load power total kh7",
            "kw",
            "power",
        ),
        candidate(
            "sensor.kh7_grid_consumption",
            "foxess_modbus",
            "sensor",
            "foxess modbus kh7 grid consumption kh7",
            "kw",
            "power",
        ),
        candidate(
            "sensor.kh7_grid_consumption_energy_today",
            "foxess_modbus",
            "sensor",
            "foxess modbus kh7 grid consumption energy today kh7",
            "kwh",
            "energy",
        ),
        candidate(
            "sensor.octopus_energy_electricity_meter_current_demand",
            "octopus_energy",
            "sensor",
            "electricity meter current demand electricity",
            "w",
            "power",
        ),
    ]

    result = discovery.discover_from_candidates(candidates)

    assert result.mappings[constants.CONF_HOUSE_LOAD] == "sensor.kh7_load_power"
    assert result.mappings[constants.CONF_GRID_IMPORT] == "sensor.kh7_grid_consumption"
    assert constants.CONF_HOUSE_LOAD not in result.ambiguous
    assert constants.CONF_GRID_IMPORT not in result.ambiguous


def test_site_only_unit_contract_does_not_require_absent_battery() -> None:
    """Solar commissioning can prove raw site units before a battery is installed."""
    evidence = assess_foxess_unit_contract(
        {
            "solar_power_kw": "kW",
            "house_load_kw": "kW",
            "grid_import_kw": "kW",
            "grid_export_kw": "kW",
        },
        battery_required=False,
    )

    assert evidence.ready is True
    assert evidence.required_fields == 4
    assert evidence.missing_fields == ()


def test_site_only_telemetry_stability_ignores_intentionally_absent_battery() -> None:
    """Battery stale fields must not block sustained site telemetry evidence."""
    start = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    records = [_record(start + timedelta(seconds=30 * index)) for index in range(12)]

    evidence = assess_foxess_telemetry_stability(
        records,
        expected_interval_seconds=30,
        battery_required=False,
    )

    assert evidence.ready is True
    assert evidence.state == "stable"
    assert evidence.complete_samples == 12
    assert evidence.missing_fields == ()
    assert evidence.stale_fields == ()


def test_site_only_power_balance_proves_solar_grid_and_house_without_battery() -> None:
    """Whole-site conservation remains provable with battery flow fixed at zero."""
    start = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
    records = [_record(start + timedelta(seconds=30 * index)) for index in range(12)]

    evidence = assess_foxess_power_balance(
        records,
        positive_is_discharge=True,
        battery_required=False,
    )

    assert evidence.ready is True
    assert evidence.state == "balanced"
    assert evidence.eligible_samples == 12
    assert evidence.balance_percent == 100.0


def test_solar_only_commissioning_remains_read_only_and_defers_battery_proof() -> None:
    """The interim stage may prove site telemetry but can never unlock control."""
    content = COMMISSIONING.read_text(encoding="utf-8")
    assert "solar_only_commissioning" in content
    assert "battery_installation_pending" in content
    assert '"ready_for_control": False' in content
    assert '"real_hardware_writes": "blocked"' in content
    assert '"maximum_allowed_stage": "shadow"' in content


def test_alpha930_versions_core_only_panel_remains_alpha9_panel3() -> None:
    """Alpha9.30 advances core while retaining the live-proven panel firmware."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    panel = PANEL.read_text(encoding="utf-8")

    assert manifest["version"] == "0.9.0-alpha9.30"
    assert bundle["bundle_version"] == "0.9.0-alpha9.30"
    assert bundle["components"]["panel"]["version"] == "0.9.0-alpha9-panel.3"
    assert 'PANEL_CONFIG_VERSION = "0.9.0-alpha9-panel.3"' in panel
