"""Alpha9.5 presentation contracts plus Alpha9.6-Alpha9.10 recovery hardening."""

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
PANEL_SOURCE_PATH = KEMS / "agile_panel_presentation_runtime.py"


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
        "_HOME_RECONCILED_OLD",
        "_HOME_RECONCILED_NEW",
        "_KEMS_DAILY_CARD_NEW",
        "_COMPARE_WITHOUT_KEMS_NEW",
        "_COMPARE_LIVE_NEW",
        "_COMPARE_KEMS_NEW",
        "_COMPARE_SIDE_BY_SIDE_NEW",
    }
    functions = {
        "_replace_between",
        "_improve_alpha910_today_presentation",
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


def _panel_runtime_fixture() -> SimpleNamespace:
    """Load frozen panel formatting helpers without importing Home Assistant."""
    tree = ast.parse(PANEL_SOURCE_PATH.read_text(encoding="utf-8"))
    assignments = {
        "_LIVE_SENSOR",
        "_LEGACY_PANEL_FLOW_SENSOR",
        "_PANEL_FLOW_SENSOR",
    }
    functions = {"_number", "_value", "_compact_flow"}
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
    exec(compile(module, str(PANEL_SOURCE_PATH), "exec"), namespace)
    return SimpleNamespace(
        _LIVE_SENSOR=namespace["_LIVE_SENSOR"],
        _LEGACY_PANEL_FLOW_SENSOR=namespace["_LEGACY_PANEL_FLOW_SENSOR"],
        _PANEL_FLOW_SENSOR=namespace["_PANEL_FLOW_SENSOR"],
        _compact_flow=namespace["_compact_flow"],
    )


def _alpha98_projection_helpers() -> dict[str, Any]:
    """Load Alpha9.8's standalone projection helpers against the frozen formatter."""
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    names = {
        "_finite",
        "_state_with_panel_soc",
        "_panel_flow",
        "_publish_panel_flow_state",
        "publish_alpha98_panel_projection",
    }
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            assigned = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if "_SIMULATED_SOC_ENTITY" in assigned:
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            body.append(node)

    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    namespace: dict[str, Any] = {
        "Any": Any,
        "math": math,
        "panel_runtime": _panel_runtime_fixture(),
    }
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


def test_alpha98_panel_soc_accepts_explicit_startup_virtual_soc() -> None:
    helper = _pure_helpers()["_state_with_panel_soc"]

    class States:
        @staticmethod
        def get(_entity_id: str):
            raise AssertionError(
                "HA fallback must not be queried when startup SOC exists"
            )

    manager = SimpleNamespace(_hass=SimpleNamespace(states=States()))
    original = {
        "current_routing_snapshot": {
            "available": False,
            "simulated_soc_percent": None,
        }
    }

    enriched = helper(manager, original, 68.6)

    assert enriched["current_routing_snapshot"]["simulated_soc_percent"] == 68.6
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


def test_alpha97_panel_projection_is_standalone_and_preserves_soc() -> None:
    helper = _alpha98_projection_helpers()["_publish_panel_flow_state"]
    writes: list[tuple[str, object, dict[str, Any]]] = []

    class States:
        @staticmethod
        def get(entity_id: str):
            assert entity_id == "sensor.kems_agile_live_scenario"
            return SimpleNamespace(state="ready", attributes={"existing": True})

    manager = SimpleNamespace(
        _hass=SimpleNamespace(states=States()),
        _set=lambda entity_id, state, attributes: writes.append(
            (entity_id, state, attributes)
        ),
    )
    state = {
        "current_routing_snapshot": {
            "available": True,
            "simulated_house_load_kw": 1.2,
            "solar_power_kw": 0.5,
            "grid_import_kw": 0.0,
            "grid_export_kw": 0.3,
            "solar_to_home_kw": 0.5,
            "solar_to_battery_kw": 0.0,
            "solar_export_kw": 0.0,
            "grid_to_battery_kw": 0.0,
            "battery_to_home_kw": 0.7,
            "battery_export_kw": 0.3,
            "simulated_soc_percent": 76.0,
            "routing_action": "HOME/EXPORT",
            "dispatch_mode": "battery",
        }
    }

    helper(manager, state)

    assert [item[0] for item in writes] == [
        "sensor.kems_agile_smart_export_flow_now",
        "sensor.kems_panel_full_kems_agile_flow_now",
        "sensor.kems_agile_live_scenario",
    ]
    assert "SOC=76.0" in str(writes[0][1])
    assert writes[0][2]["simulated_soc_percent"] == 76.0
    assert writes[2][2]["panel_flow_source"] == (
        "sensor.kems_panel_full_kems_agile_flow_now"
    )


def test_alpha98_unavailable_panel_flow_keeps_only_valid_virtual_soc() -> None:
    helper = _alpha98_projection_helpers()["_panel_flow"]
    flow = helper(
        {
            "available": False,
            "simulated_soc_percent": 68.6,
        }
    )

    assert flow == (
        "H=-1,S=-1,GI=-1,GE=-1,SH=-1,SB=-1,SE=-1," "GB=-1,BH=-1,BE=-1,SOC=68.6"
    )


def test_alpha98_explicit_startup_projection_republishes_panel_soc() -> None:
    helper = _alpha98_projection_helpers()["publish_alpha98_panel_projection"]
    writes: list[tuple[str, object, dict[str, Any]]] = []

    class States:
        @staticmethod
        def get(entity_id: str):
            assert entity_id == "sensor.kems_agile_live_scenario"
            return None

    manager = SimpleNamespace(
        state={
            "current_routing_snapshot": {
                "available": False,
                "simulated_soc_percent": None,
            }
        },
        _hass=SimpleNamespace(states=States()),
        _set=lambda entity_id, state, attributes: writes.append(
            (entity_id, state, attributes)
        ),
    )

    helper(manager, 68.6)

    assert len(writes) == 2
    assert writes[0][1].endswith("SOC=68.6")
    assert writes[1][1].endswith("SOC=68.6")


def test_alpha97_install_never_reinstalls_legacy_panel_wrapper() -> None:
    repair = SOURCE_PATH.read_text(encoding="utf-8")
    panel = PANEL_SOURCE_PATH.read_text(encoding="utf-8")
    product = (KEMS / "agile_product_presentation.py").read_text(encoding="utf-8")
    install = repair[repair.index("def install_alpha95_presentation()") :]

    assert "install_alpha736_panel_flow_patch" not in repair
    assert "install_alpha736_panel_flow_patch()" in product
    assert "def _publish_panel_flow_state" in repair
    assert "_publish_panel_flow_state(self, enriched)" in install
    assert install.index("original_publish(self, state)") < install.index(
        "enriched = _state_with_panel_soc(self, state)"
    )
    assert install.index(
        "enriched = _state_with_panel_soc(self, state)"
    ) < install.index("_publish_panel_flow_state(self, enriched)")
    assert "publish_with_alpha95_panel_soc._kems_alpha736_panel_flow = True" in install
    assert "alpha736_original_publish = publish" in panel


def test_alpha96_install_remains_retry_safe() -> None:
    repair = SOURCE_PATH.read_text(encoding="utf-8")
    install = repair[repair.index("def install_alpha95_presentation()") :]

    guard = 'if getattr(publish, "_kems_alpha95_panel_soc", False):'
    assert guard in install
    assert (
        "dashboard._combined_master_dashboard_bytes = dashboard_bytes_with_alpha95"
        in install
    )
    assert (
        "convergent._managed_dashboard_bytes = dashboard_bytes_with_alpha95" in install
    )


def test_alpha98_setup_recovers_sources_and_reprojects_panel_before_platforms() -> None:
    setup = (KEMS / "__init__.py").read_text(encoding="utf-8")

    assert setup.count("async_recover_alpha98_startup_sources(hass, coordinator)") == 1
    assert setup.count("publish_alpha98_panel_projection(") == 1
    call = setup.index("publish_alpha98_panel_projection(\n")
    platforms = setup.index("await hass.config_entries.async_forward_entry_setups")
    assert call < platforms


def test_alpha95_installs_before_dashboard_sync_and_restores_panel_flow() -> None:
    setup = (KEMS / "__init__.py").read_text(encoding="utf-8")
    repair = SOURCE_PATH.read_text(encoding="utf-8")

    assert "install_alpha95_presentation()" in setup
    assert setup.index("install_alpha95_presentation()") < setup.index(
        "await async_sync_managed_dashboard(hass)"
    )
    assert "_publish_panel_flow_state" in repair
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
