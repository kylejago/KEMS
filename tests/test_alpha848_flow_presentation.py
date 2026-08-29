"""Regression contract for Alpha8.48 slot-flow presentation/accounting."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def _load_modules():
    """Load the Agile runtime without requiring Home Assistant in unit tests."""
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientError = type("ClientError", (Exception,), {})
    sys.modules.setdefault("aiohttp", aiohttp)

    homeassistant = types.ModuleType("homeassistant")
    homeassistant.__path__ = []
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        def __class_getitem__(cls, item):
            return cls

    storage.Store = Store
    sys.modules.setdefault("homeassistant", homeassistant)
    sys.modules.setdefault("homeassistant.core", core)
    sys.modules.setdefault("homeassistant.helpers", helpers)
    sys.modules.setdefault("homeassistant.helpers.aiohttp_client", aiohttp_client)
    sys.modules.setdefault("homeassistant.helpers.storage", storage)

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = types.ModuleType("custom_components.kems")
    package.__path__ = [str(INTEGRATION)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.kems", package)

    agile_name = "custom_components.kems.agile_smart_export"
    spec = importlib.util.spec_from_file_location(
        agile_name,
        INTEGRATION / "agile_smart_export.py",
    )
    assert spec is not None and spec.loader is not None
    agile = importlib.util.module_from_spec(spec)
    sys.modules[agile_name] = agile
    spec.loader.exec_module(agile)

    flow = importlib.import_module("custom_components.kems.agile_flow_presentation")
    slot_flow = importlib.import_module("custom_components.kems.kems_core.slot_flow")
    return flow, slot_flow


def test_user_example_reconciles_grid_solar_and_battery() -> None:
    """The dashboard must preserve the exact source breakdown requested live."""
    _, slot_flow = _load_modules()
    flow = slot_flow.build_slot_flow(
        grid_import_kwh=0.0,
        solar_generation_kwh=2.3,
        solar_to_home_kwh=0.5,
        solar_to_battery_kwh=0.0,
        solar_export_kwh=1.8,
        grid_to_battery_kwh=0.0,
        battery_to_home_kwh=0.0,
        battery_export_kwh=2.1,
        estimated_soc_percent=72.4,
        basis="regression fixture",
    )

    assert flow["flow_grid_action"] == "EXPO"
    assert flow["flow_grid_export_kwh"] == 3.9
    assert flow["flow_grid_kwh"] == 3.9
    assert flow["flow_solar_action"] == "HOME/EXPO"
    assert flow["flow_solar_kwh"] == 2.3
    assert flow["flow_solar_to_home_kwh"] == 0.5
    assert flow["flow_solar_export_kwh"] == 1.8
    assert flow["flow_battery_action"] == "EXPO"
    assert flow["flow_battery_kwh"] == 2.1
    assert flow["flow_battery_export_kwh"] == 2.1
    assert flow["flow_estimated_soc_percent"] == 72.4
    assert all(flow["flow_checks"].values())


def test_slot_flow_reports_mixed_routes_and_charge() -> None:
    _, slot_flow = _load_modules()
    flow = slot_flow.build_slot_flow(
        grid_import_kwh=3.0,
        solar_generation_kwh=1.5,
        solar_to_home_kwh=0.5,
        solar_to_battery_kwh=1.0,
        solar_export_kwh=0.0,
        grid_to_battery_kwh=2.0,
        battery_to_home_kwh=0.0,
        battery_export_kwh=0.0,
        estimated_soc_percent=40.0,
        basis="regression fixture",
    )

    assert flow["flow_grid_action"] == "IMPORT"
    assert flow["flow_grid_kwh"] == 3.0
    assert flow["flow_solar_action"] == "HOME/BATT"
    assert flow["flow_solar_kwh"] == 1.5
    assert flow["flow_battery_action"] == "CHARGE"
    assert flow["flow_battery_charge_kwh"] == 3.0
    assert flow["flow_battery_kwh"] == 3.0
    assert all(flow["flow_checks"].values())


def test_live_today_export_keeps_replay_solar_but_only_settled_battery() -> None:
    flow_module, _ = _load_modules()
    now = datetime(2026, 8, 29, 9, 18, tzinfo=UTC)
    state = {
        "battery_wear_assumption_pence_per_discharged_kwh": 2.0,
        "today_slots": [
            {
                "valid_from": "2026-08-29T08:30:00+00:00",
                "valid_to": "2026-08-29T09:00:00+00:00",
                "rate_pence": 15.0,
                "solar_export_kwh": 0.20,
                "battery_export_kwh": 0.10,
                "settlement_source": "completed shadow outcome",
            },
            {
                "valid_from": "2026-08-29T09:00:00+00:00",
                "valid_to": "2026-08-29T09:30:00+00:00",
                "rate_pence": 20.0,
                "solar_export_kwh": 0.15,
                # Deliberately non-zero: current/future plan, not settlement.
                "battery_export_kwh": 2.10,
            },
        ],
        "periods": {
            "today": {
                "agile_smart_export": {
                    "ready": True,
                    "grid_export_kwh": 0.30,
                    "solar_export_kwh": 0.20,
                    "battery_export_kwh": 0.10,
                    "battery_to_home_kwh": 1.0,
                    "import_cost_pence": 100.0,
                    "export_income_pence": 3.0,
                    "energy_net_cost_pence": 150.0,
                }
            }
        },
    }

    flow_module._live_replay_solar_accounting(state, now=now)

    today = state["periods"]["today"]["agile_smart_export"]
    assert today["solar_export_kwh"] == 0.35
    assert today["battery_export_kwh"] == 0.10
    assert today["grid_export_kwh"] == 0.45
    assert today["export_income_pence"] == 6.0
    assert today["grid_export_accounting_source"] == (
        "live replay solar + completed settled battery export"
    )
    diagnostic = state["current_day_settlement_reconciliation"]
    assert diagnostic["settled_slots_accounted"] == 1
    assert diagnostic["accounting_checks"]["future_planned_battery_export_excluded"]
    assert diagnostic["all_accounting_checks_passed"]


def test_active_slot_uses_remaining_projection_contract() -> None:
    flow_module, _ = _load_modules()
    now = datetime(2026, 8, 29, 9, 18, tzinfo=UTC)
    key = "2026-08-29T09:00:00+00:00"
    state = {
        "today_slots": [
            {
                "valid_from": key,
                "valid_to": "2026-08-29T09:30:00+00:00",
                "rate_pence": 18.0,
                "ending_soc_percent": 80.0,
            }
        ],
        "tomorrow_slots": [],
    }
    future = {
        key: {
            "grid_import_kwh": 0.0,
            "solar_generation_kwh": 2.3,
            "solar_to_home_kwh": 0.5,
            "solar_to_battery_kwh": 0.0,
            "solar_export_kwh": 1.8,
            "grid_to_battery_kwh": 0.0,
            "battery_to_home_kwh": 0.0,
            "battery_export_kwh": 2.1,
            "estimated_soc_percent": 72.4,
            "basis": "KEMS forecast + final rolling allocation",
            "scope": "remaining slot",
        }
    }

    flow_module._attach_flow_contract(state, now=now, future_today=future)

    slot = state["today_slots"][0]
    assert slot["flow_scope"] == "remaining slot"
    assert slot["flow_estimated_soc_percent"] == 72.4
    assert slot["flow_grid_action"] == "EXPO"
    assert slot["flow_grid_export_kwh"] == 3.9
    assert slot["flow_solar_action"] == "HOME/EXPO"
    assert slot["flow_battery_action"] == "EXPO"


def test_alpha848_is_reporting_only_and_preserves_alpha847_owner() -> None:
    module = Path("custom_components/kems/agile_flow_presentation.py").read_text()
    runtime = Path("custom_components/kems/agile_smart_export_runtime.py").read_text()

    assert "MidnightRolloverAgileSmartExportManager" in module
    assert "FlowPresentationAgileSmartExportManager" in runtime
    assert (
        "EfficientAgileSmartExportManager = FlowPresentationAgileSmartExportManager"
        in runtime
    )
    assert "services.async_call" not in module
    assert "async_call(" not in module
    assert 'hardware_writes": "blocked' in module
    assert "foxess" not in module.lower()
