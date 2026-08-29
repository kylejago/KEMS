"""Regression contract for Alpha8.49 canonical flow/accounting authority."""

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
    """Load the Agile reporting runtime without requiring Home Assistant."""
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

    canonical = importlib.import_module(
        "custom_components.kems.agile_canonical_flow_accounting"
    )
    slot_flow = importlib.import_module("custom_components.kems.kems_core.slot_flow")
    kems_core = importlib.import_module("custom_components.kems.kems_core")
    return canonical, slot_flow, kems_core


def test_pure_export_uses_export_but_mixed_route_keeps_expo() -> None:
    _, slot_flow, _ = _load_modules()
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
        basis="Alpha8.49 regression",
    )

    assert flow["flow_grid_action"] == "EXPORT"
    assert flow["flow_solar_action"] == "HOME/EXPO"
    assert flow["flow_battery_action"] == "EXPORT"
    assert flow["flow_grid_export_kwh"] == 3.9
    assert all(flow["flow_checks"].values())


def test_active_slot_mirrors_canonical_current_routing_snapshot() -> None:
    canonical, _, kems_core = _load_modules()
    state = {
        "today_slots": [
            {
                "valid_from": "2026-08-29T13:00:00+00:00",
                "valid_to": "2026-08-29T13:30:00+00:00",
                "flow_estimated_soc_percent": 75.2,
                # Alpha8.48's conflicting presentation is intentionally present.
                "flow_solar_action": "HOME/BATT",
                "flow_solar_to_battery_kwh": 0.891,
            }
        ],
        "current_routing_snapshot": {
            "available": True,
            "generated_at": "2026-08-29T14:06:07.242295+01:00",
            "routing_valid_from": "2026-08-29T13:00:00+00:00",
            "routing_valid_to": "2026-08-29T13:30:00+00:00",
            "simulated_soc_percent": 73.572,
            "grid_import_kw": 0.0,
            "grid_export_kw": 2.031,
            "solar_power_kw": 3.723,
            "solar_to_home_kw": 1.692,
            "solar_to_battery_kw": 0.0,
            "solar_export_kw": 2.031,
            "grid_to_battery_kw": 0.0,
            "battery_to_home_kw": 0.0,
            "battery_export_kw": 0.0,
        },
    }
    config = kems_core.SimulationConfig()
    now = datetime(2026, 8, 29, 13, 6, 7, 242295, tzinfo=UTC)

    canonical._active_slot_from_routing(state, now=now, config=config)

    slot = state["today_slots"][0]
    remaining_hours = (30 * 60 - (6 * 60 + 7.242295)) / 3600.0
    assert slot["flow_basis"] == "canonical current routing snapshot"
    assert slot["flow_scope"] == "remaining slot"
    assert slot["flow_routing_authority"] == "current_routing_snapshot"
    assert slot["flow_grid_action"] == "EXPORT"
    assert slot["flow_solar_action"] == "HOME/EXPO"
    assert slot["flow_battery_action"] == "IDLE"
    assert slot["flow_grid_export_kwh"] == round(2.031 * remaining_hours, 3)
    assert slot["flow_solar_to_home_kwh"] == round(1.692 * remaining_hours, 3)
    assert slot["flow_solar_export_kwh"] == round(2.031 * remaining_hours, 3)
    assert slot["flow_solar_to_battery_kwh"] == 0.0
    assert all(slot["flow_checks"].values())


def test_captured_live_solar_survives_completed_slot_settlement() -> None:
    canonical, _, _ = _load_modules()
    now = datetime(2026, 8, 29, 13, 6, tzinfo=UTC)
    state = {
        "battery_wear_assumption_pence_per_discharged_kwh": 2.0,
        "today_slots": [
            {
                "valid_from": "2026-08-29T12:00:00+00:00",
                "valid_to": "2026-08-29T12:30:00+00:00",
                "rate_pence": 20.0,
                "battery_export_kwh": 0.2,
            },
            {
                "valid_from": "2026-08-29T13:00:00+00:00",
                "valid_to": "2026-08-29T13:30:00+00:00",
                "rate_pence": 14.45,
                "battery_export_kwh": 0.0,
            },
        ],
        "periods": {
            "today": {
                "agile_smart_export": {
                    "ready": True,
                    "solar_export_kwh": 0.25,
                    "battery_export_kwh": 0.2,
                    "grid_export_kwh": 0.45,
                    "battery_to_home_kwh": 1.0,
                    "import_cost_pence": 100.0,
                    "export_income_pence": 10.0,
                    "energy_net_cost_pence": 150.0,
                    "economic_net_cost_pence": 152.4,
                },
                "full_kems_forecast": {
                    "ready": True,
                    "economic_net_cost_pence": 200.0,
                },
                "comparison": {},
            }
        },
    }

    capture = canonical._capture_live_replay_accounting(state, now=now)
    assert capture is not None
    assert capture["solar_export_kwh"] == 0.25
    assert capture["completed_replay_battery_income_pence"] == 4.0

    # Model the completed digital-twin settlement replacing replay battery export.
    state["today_slots"][0]["battery_export_kwh"] = 0.3
    state["today_slots"][0]["settlement_source"] = "settled shadow outcome"
    state["current_day_settlement_reconciliation"] = {
        "battery_export_kwh": 0.3,
        "accounting_checks": {
            "future_planned_export_excluded": True,
            "grid_export_balance": True,
        },
    }
    today = state["periods"]["today"]["agile_smart_export"]
    today.update(
        {
            "solar_export_kwh": 0.0,
            "battery_export_kwh": 0.3,
            "grid_export_kwh": 0.3,
            "export_income_pence": 6.0,
            "energy_net_cost_pence": 154.0,
            "economic_net_cost_pence": 156.6,
        }
    )

    canonical._apply_captured_live_solar_accounting(
        state,
        now=now,
        capture=capture,
    )

    today = state["periods"]["today"]["agile_smart_export"]
    assert today["solar_export_kwh"] == 0.25
    assert today["battery_export_kwh"] == 0.3
    assert today["grid_export_kwh"] == 0.55
    assert today["export_income_pence"] == 12.0
    assert today["grid_export_accounting_source"] == (
        "captured live replay solar + completed settled battery export"
    )
    diagnostic = state["current_day_settlement_reconciliation"]
    assert diagnostic["live_solar_capture_preserved"]
    assert diagnostic["accounting_checks"]["future_planned_battery_export_excluded"]
    assert diagnostic["all_accounting_checks_passed"]


def test_alpha849_is_reporting_only_above_alpha848() -> None:
    module = Path(
        "custom_components/kems/agile_canonical_flow_accounting.py"
    ).read_text()
    runtime = Path("custom_components/kems/agile_smart_export_runtime.py").read_text()

    assert "FlowPresentationAgileSmartExportManager" in module
    assert "CanonicalFlowAccountingAgileSmartExportManager" in runtime
    owner_assignment = (
        "EfficientAgileSmartExportManager = "
        "CanonicalFlowAccountingAgileSmartExportManager"
    )
    assert owner_assignment in runtime
    assert "services.async_call" not in module
    assert "async_call(" not in module
    assert 'hardware_writes": "blocked' in module
    assert "providers.foxess" not in module
