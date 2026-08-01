"""Tests for provider-independent Ohme and FoxESS helpers."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from kems_core import (
    calculate_battery_power_kw,
    interpret_charger_status,
    normalise_grid_power,
)


def test_ohme_status_is_interpreted() -> None:
    """The current Ohme enum status should drive connected/charging flags."""
    assert interpret_charger_status("charging") == (True, True)
    assert interpret_charger_status("plugged_in") == (True, False)
    assert interpret_charger_status("pending_approval") == (True, False)
    assert interpret_charger_status("unplugged") == (False, False)


def test_unknown_ohme_status_is_safe() -> None:
    """Unknown status values should not create false observations."""
    assert interpret_charger_status(None) == (None, None)
    assert interpret_charger_status("unavailable") == (None, None)
    assert interpret_charger_status("future_state") == (None, None)


def test_foxess_battery_power_can_be_derived() -> None:
    """FoxESS voltage and current can provide battery power when needed."""
    assert calculate_battery_power_kw(400.0, 10.0) == 4.0
    assert calculate_battery_power_kw(400.0, -10.0) == -4.0
    assert calculate_battery_power_kw(None, 10.0) is None


def test_grid_power_normalisation_never_exposes_negative_import_or_export() -> None:
    """Signed and duplicate sources should become clear positive magnitudes."""
    importing = normalise_grid_power(0.573, None)
    assert importing.import_kw == 0.573
    assert importing.export_kw == 0.0

    exporting = normalise_grid_power(-2.5, None)
    assert exporting.import_kw == 0.0
    assert exporting.export_kw == 2.5

    duplicate = normalise_grid_power(-3.2, -3.2)
    assert duplicate.import_kw == 0.0
    assert duplicate.export_kw == 3.2
    assert duplicate.mode == "duplicate_signed_source_export"

    separate = normalise_grid_power(1.1, 0.4)
    assert separate.import_kw == 1.1
    assert separate.export_kw == 0.4


def test_entity_map_rejects_kems_generated_sources() -> None:
    """Direct config-entry parsing must also block circular KEMS inputs."""
    integration = Path(__file__).parents[1] / "custom_components" / "kems"
    package_name = "kems_entity_map_test"
    package = ModuleType(package_name)
    package.__path__ = [str(integration)]
    providers = ModuleType(f"{package_name}.providers")
    providers.__path__ = [str(integration / "providers")]
    sys.modules[package_name] = package
    sys.modules[f"{package_name}.providers"] = providers

    for module_name, path in (
        ("const", integration / "const.py"),
        ("providers.entity_map", integration / "providers" / "entity_map.py"),
    ):
        qualified_name = f"{package_name}.{module_name}"
        spec = importlib.util.spec_from_file_location(qualified_name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified_name] = module
        spec.loader.exec_module(module)

    entity_map = sys.modules[f"{package_name}.providers.entity_map"]
    entities = entity_map.KEMSEntities.from_entry_data(
        {
            "grid_export_kw": "sensor.kems_simulated_grid_export_power",
            "battery_power_kw": "sensor.kems_simulated_battery_power",
            "current_import_rate": "sensor.octopus_current_rate",
        }
    )

    assert entities.grid_export_kw is None
    assert entities.battery_power_kw is None
    assert entities.current_import_rate == "sensor.octopus_current_rate"
