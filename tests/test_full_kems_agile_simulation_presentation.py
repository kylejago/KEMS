"""Regression coverage for the canonical adaptive-KEMS Agile sensor projection."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).parents[1]
KEMS_ROOT = ROOT / "custom_components" / "kems"
PACKAGE = "kems_agile_presentation_test"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package = ModuleType(PACKAGE)
package.__path__ = [str(KEMS_ROOT)]
sys.modules[PACKAGE] = package
product_types = _load(f"{PACKAGE}.product_types", KEMS_ROOT / "product_types.py")
presentation = _load(
    f"{PACKAGE}.agile_simulation_presentation",
    KEMS_ROOT / "agile_simulation_presentation.py",
)

FULL_KEMS_AGILE = "full_kems_agile"
BATTERY_SOLAR = "battery_solar"


def _coordinator(system_type: str = FULL_KEMS_AGILE):
    state = {
        "current_rate_pence": 12.94,
        "rolling_export_plan": {
            "current_battery_export_target_kw": 1.5,
            "exportable_battery_energy_kwh": 8.2,
            "protected_house_energy_kwh": 4.1,
        },
        "current_routing_snapshot": {
            "available": True,
            "simulated_house_load_kw": 0.8,
            "solar_power_kw": 0.0,
            "grid_import_kw": 7.8,
            "grid_export_kw": 0.0,
            "solar_to_battery_kw": 0.0,
            "grid_to_battery_kw": 7.0,
            "battery_to_home_kw": 0.0,
            "battery_export_kw": 0.0,
            "total_discharge_kw": 0.0,
            "normalised_kh7_ac_output_kw": 0.0,
            "simulated_soc_percent": 80.0,
            "current_agile_rate_pence": 12.94,
        },
        "periods": {
            "today": {
                "agile_smart_export": {
                    "energy_net_cost_pence": 87.31,
                    "grid_import_kwh": 38.1,
                    "grid_export_kwh": 4.14,
                    "export_income_pence": 43.69,
                    "solar_generation_kwh": 22.5,
                    "solar_curtailed_kwh": 0.0,
                    "solar_to_battery_kwh": 10.25,
                    "grid_to_battery_kwh": 36.684,
                    "battery_to_home_kwh": 8.75,
                    "battery_export_kwh": 0.39,
                    "ending_soc_percent": 79.6,
                }
            }
        },
    }
    options = {"system_type": system_type}
    return SimpleNamespace(
        entry=SimpleNamespace(options=options),
        settings=SimpleNamespace(system_type=system_type),
        agile_smart_export_state=state,
    )


def test_agile_totals_drive_existing_simulated_contract() -> None:
    coordinator = _coordinator()

    assert (
        presentation._projected_value(coordinator, "simulated_grid_import_today")
        == 38.1
    )
    assert (
        presentation._projected_value(coordinator, "simulated_grid_export_today")
        == 4.14
    )
    assert (
        presentation._projected_value(coordinator, "simulated_export_income_today")
        == 43.69
    )
    assert presentation._projected_value(coordinator, "simulated_cost_today") == 87.31
    assert (
        presentation._projected_value(coordinator, "simulated_battery_export_today")
        == 0.39
    )
    assert (
        presentation._projected_value(coordinator, "simulated_battery_charge_today")
        == 46.934
    )


def test_overnight_grid_charge_is_visible_as_negative_battery_power() -> None:
    coordinator = _coordinator()

    assert (
        presentation._projected_value(coordinator, "simulated_grid_import_power") == 7.8
    )
    assert (
        presentation._projected_value(coordinator, "simulated_battery_charging_power")
        == 7.0
    )
    assert presentation._projected_value(coordinator, "simulated_battery_power") == -7.0
    assert presentation._projected_value(coordinator, "simulated_grid_net_power") == 7.8
    assert presentation._projected_value(coordinator, "simulated_battery_soc") == 80.0


def test_agile_current_export_projects_to_generic_graph_contract() -> None:
    coordinator = _coordinator()
    routing = coordinator.agile_smart_export_state["current_routing_snapshot"]
    routing.update(
        {
            "grid_import_kw": 0.0,
            "grid_export_kw": 3.4,
            "grid_to_battery_kw": 0.0,
            "battery_to_home_kw": 0.6,
            "battery_export_kw": 3.4,
            "total_discharge_kw": 4.0,
            "normalised_kh7_ac_output_kw": 4.0,
        }
    )

    assert (
        presentation._projected_value(coordinator, "simulated_grid_export_power") == 3.4
    )
    assert (
        presentation._projected_value(coordinator, "simulated_grid_net_power") == -3.4
    )
    assert presentation._projected_value(coordinator, "simulated_battery_power") == 4.0
    assert (
        presentation._projected_value(coordinator, "simulated_battery_export_power")
        == 3.4
    )


def test_non_agile_tariff_keeps_original_simulation_contract() -> None:
    coordinator = _coordinator(BATTERY_SOLAR)

    assert (
        presentation._projected_value(coordinator, "simulated_grid_export_today")
        is presentation._MISSING
    )
    assert (
        presentation._projected_value(coordinator, "simulated_battery_power")
        is presentation._MISSING
    )


def test_explicit_agile_tariff_drives_projection_for_unified_kems_product() -> None:
    coordinator = _coordinator("kems")
    coordinator.entry.options = {
        "system_type": "kems",
        "export_tariff_type": product_types.EXPORT_TARIFF_TYPE_AGILE,
    }
    assert (
        presentation._projected_value(coordinator, "simulated_grid_export_today")
        == 4.14
    )


def test_presentation_projection_is_reporting_only_and_canonically_named() -> None:
    source = presentation.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")

    assert 'hardware_writes": "blocked' in text
    assert "base_simulation_state_preserved" in text
    assert "commands_permitted = True" not in text
    assert "safe_to_write_hardware = True" not in text
    assert ".services.async_call(" not in text
    assert "alpha8.1" not in source.lower()
    assert "alpha81" not in source.lower()
