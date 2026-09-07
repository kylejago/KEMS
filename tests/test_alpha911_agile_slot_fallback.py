"""Alpha9.11 Agile slot replay fallback contracts."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from kems_core import SimulationConfig, Snapshot
from kems_core import simulation as simulation_module
from kems_core.simulation_fallback import (
    apply_simulation_demand_fallback,
    install_simulation_demand_fallback_policy,
)

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
SOURCE = KEMS / "agile_slot_simulation_fallback.py"


def _helpers() -> dict[str, Any]:
    """Load the HA-independent repair helpers with lightweight collaborators."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    names = {"_simulation_load", "_fallback_aware_observed_slot_details"}
    body = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))

    def rate_at(rates: list[Any], timestamp: datetime) -> Any | None:
        return next(
            (rate for rate in rates if rate.valid_from <= timestamp < rate.valid_to),
            None,
        )

    namespace: dict[str, Any] = {
        "Any": Any,
        "Snapshot": Snapshot,
        "SimulationConfig": SimulationConfig,
        "simulation_module": simulation_module,
        "agile": SimpleNamespace(_rate_at=rate_at),
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


def _fallback_snapshot(timestamp: datetime, demand_kw: float) -> Snapshot:
    evidence = apply_simulation_demand_fallback(
        physical_house_load_kw=None,
        physical_grid_import_kw=None,
        physical_source_age_seconds={
            "battery_soc": 3600.0,
            "battery_power_kw": 3600.0,
            "solar_power_kw": 3600.0,
            "grid_export_kw": 3600.0,
        },
        physical_stale_fields=(
            "battery_power_kw",
            "battery_soc",
            "grid_export_kw",
            "solar_power_kw",
        ),
        fallback_demand_kw=demand_kw,
        fallback_age_seconds=15.0,
    )
    return Snapshot(
        timestamp=timestamp,
        current_import_rate=28.3,
        next_import_rate=28.3,
        off_peak=False,
        house_load_kw=evidence.house_load_kw,
        grid_import_kw=evidence.grid_import_kw,
        battery_soc=None,
        battery_power_kw=None,
        solar_power_kw=None,
        grid_export_kw=None,
        source_age_seconds=evidence.source_age_seconds,
        stale_fields=evidence.stale_fields,
        source_data_age_seconds=3600.0,
    )


def test_agile_slot_load_accepts_explicit_simulation_fallback_only() -> None:
    install_simulation_demand_fallback_policy()
    load = _helpers()["_simulation_load"]
    snapshot = _fallback_snapshot(datetime(2026, 9, 7, 10, 0, tzinfo=UTC), 0.8)

    assert "battery_soc" in snapshot.stale_fields
    assert "solar_power_kw" in snapshot.stale_fields
    assert load(snapshot) == 0.8

    unmarked = Snapshot.from_dict(
        {
            **snapshot.to_dict(),
            "source_age_seconds": {
                key: value
                for key, value in snapshot.source_age_seconds.items()
                if not key.startswith("simulation_fallback_")
            },
        }
    )
    assert load(unmarked) is None


def test_agile_slot_details_ignore_unrelated_physical_staleness() -> None:
    install_simulation_demand_fallback_policy()
    helper = _helpers()["_fallback_aware_observed_slot_details"]
    start = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
    records = [
        _fallback_snapshot(start, 0.8),
        _fallback_snapshot(start + timedelta(minutes=15), 1.0),
        _fallback_snapshot(start + timedelta(minutes=30), 1.2),
    ]
    rates = [
        SimpleNamespace(
            valid_from=start,
            valid_to=start + timedelta(minutes=30),
        )
    ]
    manager = SimpleNamespace(
        _simulation=SimpleNamespace(
            _simulated_solar_power=lambda _snapshot, _config: 0.5
        )
    )

    details = helper(
        manager,
        records,
        rates,
        SimulationConfig(inverter_limit_kw=7.0),
    )

    slot = details[start.isoformat()]
    assert slot["house_load_kwh"] == 0.45
    assert slot["solar_generation_kwh"] == 0.25
    assert slot["solar_to_home_kwh"] == 0.25


def test_alpha911_is_reporting_only_and_installed_from_product_presentation() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    product = (KEMS / "agile_product_presentation.py").read_text(encoding="utf-8")

    assert "simulation_module._fresh_snapshot_value" in source
    assert "current.stale_fields" not in source
    assert "following.stale_fields" not in source
    assert "install_agile_slot_simulation_fallback()" in product

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
