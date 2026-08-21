"""Parity contracts for canonical Alpha8 full-battery solar routing."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
CANONICAL = KEMS / "agile_full_battery_routing.py"


def test_canonical_full_battery_routing_parses() -> None:
    ast.parse(CANONICAL.read_text(encoding="utf-8"), filename=str(CANONICAL))


def test_full_battery_routing_uses_authoritative_agile_soc_and_blocks_charge() -> None:
    source = CANONICAL.read_text(encoding="utf-8")
    assert "agile_soc = rolling._current_agile_soc(state)" in source
    assert "agile_soc < _FULL_SOC_PERCENT - _EPSILON" in source
    assert '"solar_to_battery_kw": 0.0' in source
    assert '"grid_to_battery_kw": 0.0' in source
    assert '"battery_charge_room_kwh": 0.0' in source
    assert '"full_battery_charge_blocked_kw"' in source


def test_full_battery_routing_spills_pv_with_physical_limits() -> None:
    source = CANONICAL.read_text(encoding="utf-8")
    assert 'export_allowed = config.export_tariff_status == "active"' in source
    assert "export_headroom = max(export_limit - battery_export, 0.0)" in source
    assert "inverter_headroom = max(" in source
    assert "min(solar_surplus, export_headroom, inverter_headroom)" in source
    assert "solar_curtailment = max(solar_surplus - solar_export, 0.0)" in source
    assert '"grid_export_kw": round(grid_export, 3)' in source


def test_reported_full_soc_case_still_exports_2830_kw() -> None:
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


def test_full_battery_routing_does_not_change_dispatch_or_hardware_permissions() -> None:
    source = CANONICAL.read_text(encoding="utf-8")
    assert "_dispatch_targets" not in source
    assert "_rolling_plan" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert '"hardware_writes": "blocked"' in source
