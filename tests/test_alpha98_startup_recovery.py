"""Alpha9.8 bounded startup-source recovery contracts."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
SOURCE_PATH = KEMS / "alpha98_startup_recovery.py"
SETUP_PATH = KEMS / "__init__.py"


def _helpers() -> dict[str, Any]:
    """Load the Home Assistant-independent Alpha9.8 recovery module from source."""
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    assignments = {
        "_INVALID_STATES",
        "_FOXESS_SOURCE_MARKERS",
        "_RECOVERABLE_FIELDS",
    }
    functions = {
        "_source_state_usable",
        "_is_physical_foxess_source",
        "startup_source_recovery_fields",
        "async_recover_alpha98_startup_sources",
    }
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if names & assignments:
                body.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in functions:
                body.append(node)

    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    namespace: dict[str, Any] = {"Any": Any}
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace


class _States:
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, entity_id: str):
        value = self._values.get(entity_id)
        return None if value is None else SimpleNamespace(state=value)


def test_alpha98_detects_sources_that_arrived_during_first_analysis() -> None:
    helper = _helpers()["startup_source_recovery_fields"]
    hass = SimpleNamespace(
        states=_States(
            {
                "sensor.octopus_energy_current_demand": "660.0",
                "sensor.ohme_epod_status": "unplugged",
            }
        )
    )
    entities = SimpleNamespace(
        house_load_kw="sensor.octopus_energy_current_demand",
        grid_import_kw="sensor.octopus_energy_current_demand",
        ev_status="sensor.ohme_epod_status",
    )
    snapshot = SimpleNamespace(
        house_load_kw=None,
        grid_import_kw=None,
        ev_connected=None,
        ev_charging=None,
    )

    fields = helper(hass, entities, snapshot)

    # One physical HA entity is enough to recover all values derived from it on
    # the bounded second coordinator scan; duplicate mappings are not retried.
    assert fields == ("ev_connected", "house_load_kw")


def test_alpha98_does_not_recover_physical_foxess_sources() -> None:
    helper = _helpers()["startup_source_recovery_fields"]
    hass = SimpleNamespace(
        states=_States(
            {
                "sensor.kh7_load_power": "1.2",
                "sensor.foxess_modbus_kh7_grid_power_kh7": "0.8",
            }
        )
    )
    entities = SimpleNamespace(
        house_load_kw="sensor.kh7_load_power",
        grid_import_kw="sensor.foxess_modbus_kh7_grid_power_kh7",
    )
    snapshot = SimpleNamespace(house_load_kw=None, grid_import_kw=None)

    assert helper(hass, entities, snapshot) == ()


def test_alpha98_unknown_source_does_not_trigger_recovery() -> None:
    helper = _helpers()["startup_source_recovery_fields"]
    hass = SimpleNamespace(
        states=_States({"sensor.octopus_energy_current_demand": "unknown"})
    )
    entities = SimpleNamespace(
        house_load_kw="sensor.octopus_energy_current_demand",
        grid_import_kw="sensor.octopus_energy_current_demand",
    )
    snapshot = SimpleNamespace(house_load_kw=None, grid_import_kw=None)

    assert helper(hass, entities, snapshot) == ()


def test_alpha98_runs_exactly_one_bounded_recovery_refresh() -> None:
    helper = _helpers()["async_recover_alpha98_startup_sources"]
    calls = 0

    async def refresh() -> None:
        nonlocal calls
        calls += 1

    hass = SimpleNamespace(
        states=_States({"sensor.octopus_energy_current_demand": "660.0"})
    )
    coordinator = SimpleNamespace(
        data=SimpleNamespace(snapshot=SimpleNamespace(house_load_kw=None)),
        entities=SimpleNamespace(house_load_kw="sensor.octopus_energy_current_demand"),
        async_refresh=refresh,
    )

    fields = asyncio.run(helper(hass, coordinator))

    assert fields == ("house_load_kw",)
    assert calls == 1


def test_alpha98_setup_has_one_recovery_call_and_no_retry_loop() -> None:
    setup = SETUP_PATH.read_text(encoding="utf-8")
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert setup.count("async_recover_alpha98_startup_sources(hass, coordinator)") == 1
    assert "while " not in source
    assert "asyncio.sleep" not in source
    assert "call_later" not in source


def test_alpha98_recovery_cannot_write_hardware() -> None:
    source = SOURCE_PATH.read_text(encoding="utf-8")

    for forbidden in (
        ".services.async_call(",
        "async_select_option(",
        "async_set_native_value(",
        "write_register(",
        "write_registers(",
        "ModbusClient",
        "commands_permitted = True",
        "safe_to_write_hardware = True",
    ):
        assert forbidden not in source
