"""Alpha9.5 presentation contracts plus Alpha9.6 recovery hardening."""

from __future__ import annotations

import ast
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
DASHBOARD = ROOT / "dashboards" / "kems_master_dashboard.yaml"
SOURCE_PATH = KEMS / "alpha95_presentation.py"


def _pure_helpers() -> dict[str, Any]:
    """Load only Home Assistant-independent presentation helpers from source."""
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    assignments = {
        "_SIMULATED_SOC_ENTITY",
        "_LIVE_DAILY_OLD",
        "_LIVE_DAILY_NEW",
        "_KEMS_DAILY_OLD",
        "_KEMS_DAILY_NEW",
        "_KEMS_HOME_ENERGY_OLD",
        "_KEMS_HOME_ENERGY_NEW",
    }
    functions = {
        "improve_alpha95_dashboard",
        "_improve_dashboard_bytes",
        "_finite",
        "_state_with_panel_soc",
    }
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if names & assignments:
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in functions:
            body.append(node)

    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    namespace: dict[str, Any] = {"Any": Any, "math": math}
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace


def test_alpha95_current_day_cards_use_stable_flat_entities() -> None:
    helpers = _pure_helpers()
    content = helpers["improve_alpha95_dashboard"](
        DASHBOARD.read_text(encoding="utf-8")
    )

    assert "states('sensor.kems_whole_home_observed_cost_today')" in content
    assert "states('sensor.kems_whole_home_simulated_cost_today')" in content
    assert "states('sensor.kems_whole_home_energy_today')" in content
    assert "states('sensor.kems_observed_export_income_today')" in content
    assert "states('sensor.kems_simulated_export_income_today')" in content

    assert (
        "{% set live = p.get('live_data', {}) or {} %}\n"
        "              | Cost | Live Data |"
    ) not in content
    assert (
        "{% set kems = p.get('kems', {}) or {} %}\n" "              | Cost | KEMS |"
    ) not in content
    assert "kems.get('home_energy_kwh')" not in content


def test_alpha96_authoritative_dashboard_bytes_receive_repairs() -> None:
    helper = _pure_helpers()["_improve_dashboard_bytes"]
    content = helper(DASHBOARD.read_bytes()).decode("utf-8")

    assert "states('sensor.kems_whole_home_energy_today')" in content
    assert "u.attributes.running_kems_version" not in content
    assert "u.attributes.get('running_kems_version')" in content
    assert "u.attributes.get('last_error')" in content


def test_alpha95_panel_soc_falls_back_to_virtual_soc() -> None:
    helper = _pure_helpers()["_state_with_panel_soc"]

    class States:
        @staticmethod
        def get(entity_id: str):
            assert entity_id == "sensor.kems_simulated_battery_state_of_charge"
            return SimpleNamespace(state="76.0")

    manager = SimpleNamespace(_hass=SimpleNamespace(states=States()))
    original = {
        "current_routing_snapshot": {
            "available": True,
            "simulated_soc_percent": None,
            "battery_export_kw": 1.5,
        }
    }

    enriched = helper(manager, original)

    assert enriched is not original
    assert (
        enriched["current_routing_snapshot"] is not original["current_routing_snapshot"]
    )
    assert enriched["current_routing_snapshot"]["simulated_soc_percent"] == 76.0
    assert original["current_routing_snapshot"]["simulated_soc_percent"] is None


def test_alpha95_panel_soc_keeps_authoritative_routing_soc_when_present() -> None:
    helper = _pure_helpers()["_state_with_panel_soc"]

    class States:
        @staticmethod
        def get(_entity_id: str):
            raise AssertionError("fallback must not be queried when routing SOC exists")

    manager = SimpleNamespace(_hass=SimpleNamespace(states=States()))
    state = {"current_routing_snapshot": {"simulated_soc_percent": 42.5}}

    assert helper(manager, state) is state


def test_alpha96_install_is_retry_safe_before_legacy_panel_reinstall() -> None:
    repair = SOURCE_PATH.read_text(encoding="utf-8")
    install = repair[repair.index("def install_alpha95_presentation()") :]

    guard = 'if getattr(publish, "_kems_alpha95_panel_soc", False):'
    assert guard in install
    assert install.index(guard) < install.index("install_alpha736_panel_flow_patch()")
    assert "dashboard._combined_master_dashboard_bytes = dashboard_bytes_with_alpha95" in install
    assert "convergent._managed_dashboard_bytes = dashboard_bytes_with_alpha95" in install
    assert "publish_with_alpha95_panel_soc._kems_alpha736_panel_flow = True" in install


def test_alpha95_installs_before_dashboard_sync_and_restores_panel_flow() -> None:
    setup = (KEMS / "__init__.py").read_text(encoding="utf-8")
    repair = SOURCE_PATH.read_text(encoding="utf-8")

    assert "install_alpha95_presentation()" in setup
    assert setup.index("install_alpha95_presentation()") < setup.index(
        "await async_sync_managed_dashboard(hass)"
    )
    assert "install_alpha736_panel_flow_patch()" in repair
    assert "sensor.kems_simulated_battery_state_of_charge" in repair


def test_alpha95_presentation_repair_cannot_write_hardware() -> None:
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
