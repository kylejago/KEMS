"""Regression contract for Alpha8.50 elapsed solar and SOC continuity."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def _load_modules():
    """Load the reporting runtime without requiring Home Assistant."""
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

    continuity = importlib.import_module(
        "custom_components.kems.agile_live_solar_soc_continuity"
    )
    kems_core = importlib.import_module("custom_components.kems.kems_core")
    return continuity, kems_core


def _accounting_state(generated_at: str, solar_export_kw: float) -> dict:
    return {
        "battery_wear_assumption_pence_per_discharged_kwh": 2.0,
        "current_routing_snapshot": {
            "available": True,
            "generated_at": generated_at,
            "routing_valid_from": "2026-08-29T14:00:00+00:00",
            "routing_valid_to": "2026-08-29T14:30:00+00:00",
            "current_agile_rate_pence": 14.14,
            "solar_export_kw": solar_export_kw,
        },
        "today_slots": [
            {
                "valid_from": "2026-08-29T13:00:00+00:00",
                "valid_to": "2026-08-29T13:30:00+00:00",
                "rate_pence": 20.0,
                "battery_export_kwh": 0.3,
                "settlement_source": "settled shadow digital-twin outcome",
            },
            {
                "valid_from": "2026-08-29T14:00:00+00:00",
                "valid_to": "2026-08-29T14:30:00+00:00",
                # Remaining-slot forecast must never be counted as elapsed energy.
                "flow_solar_export_kwh": 0.702,
                "flow_scope": "remaining slot",
            },
        ],
        "periods": {
            "today": {
                "agile_smart_export": {
                    "ready": True,
                    "solar_export_kwh": 0.0,
                    "battery_export_kwh": 0.3,
                    "grid_export_kwh": 0.3,
                    "battery_to_home_kwh": 1.0,
                    "import_cost_pence": 100.0,
                    "export_income_pence": 6.0,
                    "energy_net_cost_pence": 144.0,
                    "economic_net_cost_pence": 146.6,
                },
                "full_kems_forecast": {
                    "ready": True,
                    "economic_net_cost_pence": 200.0,
                },
                "comparison": {},
            }
        },
        "current_day_settlement_reconciliation": {
            "battery_export_kwh": 0.3,
            "accounting_checks": {
                "future_planned_export_excluded": True,
                "grid_export_balance": True,
            },
        },
    }


def test_elapsed_solar_uses_canonical_samples_not_remaining_forecast() -> None:
    continuity, _ = _load_modules()
    first_now = datetime(2026, 8, 29, 14, 5, tzinfo=UTC)
    state = _accounting_state(first_now.isoformat(), 1.719)

    tracker, changed = continuity._advance_tracker(None, state, now=first_now)
    assert changed
    assert tracker["solar_export_kwh"] == 0.0
    assert tracker["tracked_increment_kwh"] == 0.0

    second_now = datetime(2026, 8, 29, 14, 6, tzinfo=UTC)
    state["current_routing_snapshot"].update(
        {
            "generated_at": second_now.isoformat(),
            "solar_export_kw": 1.8,
        }
    )
    tracker, changed = continuity._advance_tracker(tracker, state, now=second_now)
    assert changed

    expected_elapsed = ((1.719 + 1.8) / 2.0) / 60.0
    assert tracker["tracked_increment_kwh"] == pytest.approx(expected_elapsed, abs=1e-6)
    assert tracker["solar_export_kwh"] < 0.04
    assert tracker["solar_export_kwh"] != 0.702

    continuity._apply_elapsed_solar_accounting(state, tracker=tracker, now=second_now)
    today = state["periods"]["today"]["agile_smart_export"]
    assert today["solar_export_kwh"] == 0.029
    assert today["battery_export_kwh"] == 0.3
    assert today["grid_export_kwh"] == 0.329
    assert today["export_income_pence"] == pytest.approx(6.41, abs=0.01)
    diagnostic = state["current_day_settlement_reconciliation"]
    assert diagnostic["elapsed_live_solar_accounting_applied"]
    assert diagnostic["elapsed_live_solar_increment_kwh"] == 0.029
    assert diagnostic["accounting_checks"]["future_planned_battery_export_excluded"]
    assert diagnostic["all_accounting_checks_passed"]


def test_idle_active_soc_stays_canonical_and_future_soc_replays_displayed_flows() -> None:
    continuity, kems_core = _load_modules()
    now = datetime(2026, 8, 29, 14, 5, 29, tzinfo=UTC)
    state = {
        "current_routing_snapshot": {
            "available": True,
            "generated_at": now.isoformat(),
            "routing_valid_from": "2026-08-29T14:00:00+00:00",
            "routing_valid_to": "2026-08-29T14:30:00+00:00",
            "simulated_soc_percent": 75.272,
        },
        "today_slots": [
            {
                "valid_from": "2026-08-29T14:00:00+00:00",
                "valid_to": "2026-08-29T14:30:00+00:00",
                "flow_estimated_soc_percent": 76.8,
                "flow_battery_charge_kwh": 0.0,
                "flow_battery_to_home_kwh": 0.0,
                "flow_battery_export_kwh": 0.0,
            },
            {
                "valid_from": "2026-08-29T14:30:00+00:00",
                "valid_to": "2026-08-29T15:00:00+00:00",
                "flow_estimated_soc_percent": 78.6,
                "flow_battery_charge_kwh": 1.029,
                "flow_battery_to_home_kwh": 0.0,
                "flow_battery_export_kwh": 0.0,
            },
            {
                "valid_from": "2026-08-29T15:00:00+00:00",
                "valid_to": "2026-08-29T15:30:00+00:00",
                "flow_estimated_soc_percent": 73.9,
                "flow_battery_charge_kwh": 0.0,
                "flow_battery_to_home_kwh": 0.0,
                "flow_battery_export_kwh": 2.527,
            },
        ],
    }
    config = kems_core.SimulationConfig()

    continuity._rebase_display_soc(state, now=now, config=config)

    active, charging, exporting = state["today_slots"]
    assert active["flow_estimated_soc_percent"] == 75.3
    assert active["flow_soc_pre_rebase_estimate_percent"] == 76.8
    assert charging["flow_estimated_soc_percent"] == 77.1
    assert exporting["flow_estimated_soc_percent"] == 72.4
    assert state["flow_soc_continuity"]["current_soc_percent"] == 75.272
    assert state["flow_soc_continuity"]["rebased_rows"] == 3
    assert state["flow_soc_continuity"]["reporting_only"]
    assert state["flow_soc_continuity"]["hardware_writes"] == "blocked"


def test_alpha850_is_reporting_only_above_alpha849() -> None:
    module = Path(
        "custom_components/kems/agile_live_solar_soc_continuity.py"
    ).read_text()
    runtime = Path("custom_components/kems/agile_smart_export_runtime.py").read_text()

    assert "CanonicalFlowAccountingAgileSmartExportManager" in module
    assert "LiveSolarSocContinuityAgileSmartExportManager" in runtime
    owner_assignment = (
        "EfficientAgileSmartExportManager = "
        "LiveSolarSocContinuityAgileSmartExportManager"
    )
    assert owner_assignment in runtime
    assert "services.async_call" not in module
    assert "async_call(" not in module
    assert 'hardware_writes\": \"blocked' in module
    assert "providers.foxess" not in module
