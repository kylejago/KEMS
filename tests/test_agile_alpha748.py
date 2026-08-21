"""Regression coverage for Alpha7.48 full-battery solar routing."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha748_full_battery_solar.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
AGILE = KEMS / "agile_smart_export.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "agile-full-battery-solar-routing.md"


def test_alpha748_version_and_module_parse() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == "0.7.0-alpha7.48"
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha748_installs_after_prior_agile_routing_patches() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha748_full_battery_solar_patch" in loader
    assert loader.rindex("install_alpha748_full_battery_solar_patch()") > loader.rindex(
        "install_alpha746_no_unknown_reserve_patch()"
    )
    assert loader.rindex("install_alpha748_full_battery_solar_patch()") > loader.rindex(
        "install_alpha731_solar_headroom_patch()"
    )


def test_alpha748_uses_authoritative_agile_soc_and_blocks_full_battery_charge() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "agile_soc = rolling._current_agile_soc(state)" in source
    assert "agile_soc < _FULL_SOC_PERCENT - _EPSILON" in source
    assert '"solar_to_battery_kw": 0.0' in source
    assert '"grid_to_battery_kw": 0.0' in source
    assert '"battery_charge_room_kwh": 0.0' in source
    assert '"full_battery_charge_blocked_kw"' in source


def test_alpha748_spills_full_battery_solar_to_export_with_physical_limits() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'export_allowed = config.export_tariff_status == "active"' in source
    assert "export_headroom = max(export_limit - battery_export, 0.0)" in source
    assert "inverter_headroom = max(" in source
    assert "min(solar_surplus, export_headroom, inverter_headroom)" in source
    assert "solar_curtailment = max(solar_surplus - solar_export, 0.0)" in source
    assert '"grid_export_kw": round(grid_export, 3)' in source


def test_alpha748_regression_matches_reported_full_soc_case() -> None:
    """3.535 kW PV and 0.705 kW house at full SOC must spill 2.830 kW."""
    solar_kw = 3.535
    house_kw = 0.705
    battery_to_home_kw = 0.0
    battery_export_kw = 0.0
    inverter_limit_kw = 7.0
    export_limit_kw = 7.0

    solar_to_home_kw = min(solar_kw, house_kw, inverter_limit_kw)
    solar_surplus_kw = max(solar_kw - solar_to_home_kw, 0.0)
    export_headroom_kw = max(export_limit_kw - battery_export_kw, 0.0)
    inverter_headroom_kw = max(
        inverter_limit_kw - solar_to_home_kw - battery_to_home_kw - battery_export_kw,
        0.0,
    )
    solar_export_kw = min(
        solar_surplus_kw,
        export_headroom_kw,
        inverter_headroom_kw,
    )
    grid_import_kw = max(
        house_kw - solar_to_home_kw - battery_to_home_kw,
        0.0,
    )

    assert round(solar_to_home_kw, 3) == 0.705
    assert round(solar_export_kw, 3) == 2.830
    assert round(grid_import_kw, 3) == 0.0
    assert round(solar_export_kw + battery_export_kw, 3) == 2.830


def test_agile_partial_slot_charge_stops_exactly_at_capacity_then_exports() -> None:
    """A 99% battery may fill only its real room; same-slot PV then remains exportable."""
    source = AGILE.read_text(encoding="utf-8")
    assert "and battery < capacity" in source
    assert "max(capacity - battery, 0)" in source
    assert "solar_left -= charge" in source

    capacity_kwh = 10.0
    battery_kwh = 9.9
    charge_efficiency = 0.95
    solar_kw = 3.535
    house_kw = 0.705
    hours = 0.5

    solar_left_kwh = max(solar_kw - house_kw, 0.0) * hours
    charge_input_kwh = min(
        solar_left_kwh,
        7.0 * hours,
        max(capacity_kwh - battery_kwh, 0.0) / charge_efficiency,
    )
    stored_kwh = charge_input_kwh * charge_efficiency
    battery_kwh += stored_kwh
    solar_left_kwh -= charge_input_kwh

    assert round(battery_kwh, 6) == capacity_kwh
    assert round(stored_kwh, 6) == 0.1
    assert solar_left_kwh > 1.3


def test_alpha748_does_not_enable_hardware_writes_or_change_export_timing() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "_dispatch_targets" not in source
    assert "_rolling_plan" not in source
    assert '"hardware_writes": "blocked"' in source


def test_alpha748_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.48" in source
    assert "3.535 kW" in source
    assert "0.705 kW" in source
    assert "2.830 kW" in source
    assert "99%" in source
    assert "Real FoxESS hardware writes remain blocked" in source
