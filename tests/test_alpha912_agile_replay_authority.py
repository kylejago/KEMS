"""Alpha9.12 Agile replay authority regression contracts."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kems_core import Snapshot
from kems_core import simulation as simulation_module
from kems_core.simulation_fallback import (
    apply_simulation_demand_fallback,
    install_simulation_demand_fallback_policy,
)

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
SOURCE = KEMS / "agile_slot_simulation_fallback.py"
AGILE = KEMS / "agile_smart_export.py"


def _helpers() -> dict[str, Any]:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if "_PHYSICAL_ONLY_FIELDS" in names:
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {
            "_simulation_load",
            "_simulation_snapshot_view",
            "_simulation_records",
        }:
            body.append(node)
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    namespace: dict[str, Any] = {
        "Snapshot": Snapshot,
        "simulation_module": simulation_module,
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


def _fallback_snapshot(*, marked: bool = True) -> Snapshot:
    evidence = apply_simulation_demand_fallback(
        physical_house_load_kw=None,
        physical_grid_import_kw=None,
        physical_source_age_seconds={
            "battery_power_kw": 3600.0,
            "battery_soc": 3600.0,
            "grid_export_kw": 3600.0,
            "solar_power_kw": 3600.0,
        },
        physical_stale_fields=(
            "battery_power_kw",
            "battery_soc",
            "grid_export_kw",
            "solar_power_kw",
        ),
        fallback_demand_kw=0.8,
        fallback_age_seconds=15.0,
    )
    ages = dict(evidence.source_age_seconds)
    if not marked:
        ages = {
            key: value
            for key, value in ages.items()
            if not key.startswith("simulation_fallback_")
        }
    return Snapshot(
        timestamp=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
        current_import_rate=28.3,
        next_import_rate=28.3,
        off_peak=False,
        house_load_kw=evidence.house_load_kw,
        grid_import_kw=evidence.grid_import_kw,
        battery_soc=55.0,
        battery_power_kw=2.0,
        solar_power_kw=4.0,
        grid_export_kw=1.0,
        source_age_seconds=ages,
        stale_fields=evidence.stale_fields,
    )


def test_alpha912_detached_view_accepts_simulation_evidence_only() -> None:
    install_simulation_demand_fallback_policy()
    view = _helpers()["_simulation_snapshot_view"]
    physical = _fallback_snapshot(marked=True)

    adapted = view(physical)

    assert physical.stale_fields
    assert physical.solar_power_kw == 4.0
    assert adapted.stale_fields == ()
    assert adapted.house_load_kw == 0.8
    assert adapted.grid_import_kw == 0.8
    assert adapted.solar_power_kw is None
    assert adapted.battery_soc is None
    assert adapted.battery_power_kw is None
    assert adapted.grid_export_kw is None


def test_alpha912_unmarked_stale_demand_remains_fail_closed() -> None:
    install_simulation_demand_fallback_policy()
    view = _helpers()["_simulation_snapshot_view"]
    adapted = view(_fallback_snapshot(marked=False))

    assert "house_load_kw" in adapted.stale_fields
    assert "grid_import_kw" in adapted.stale_fields


def test_alpha912_replay_adapter_wraps_actual_agile_day_owner() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    agile = AGILE.read_text(encoding="utf-8")

    assert "current.stale_fields" in agile
    assert "following.stale_fields" in agile
    assert "FlowPresentationAgileSmartExportManager._agile_day" in source
    assert "_simulation_records(records)" in source
    assert "original_agile_day(" in source
    assert "snapshot.to_dict()" in source
    assert "return Snapshot.from_dict(data)" in source


def test_alpha912_does_not_change_physical_or_hardware_authority() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    for forbidden in (
        ".services.async_call(",
        "async_select_option(",
        "async_set_native_value(",
        "write_register(",
        "write_registers(",
        "commands_permitted = True",
        "safe_to_write_hardware = True",
    ):
        assert forbidden not in source
