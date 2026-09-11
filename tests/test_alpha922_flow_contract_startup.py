"""Alpha9.22 regression for the live flow-contract startup boundary."""

from __future__ import annotations

import importlib
import inspect
import json
import sys
import types
from datetime import UTC, datetime, time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def _load_modules():
    """Load the production flow stack with the suite's established HA stubs."""
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

    flow = importlib.import_module("custom_components.kems.agile_flow_presentation")
    policy = importlib.import_module("custom_components.kems.agile_flow_reserve_policy")
    models = importlib.import_module("custom_components.kems.kems_core")
    slot_flow = importlib.import_module("custom_components.kems.kems_core.slot_flow")
    tariff = importlib.import_module("custom_components.kems.tariff")
    return flow, policy, models, slot_flow, tariff


flow, policy, models, slot_flow, tariff_module = _load_modules()


def _install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the production Alpha9.22 bridge from canonical unpatched helpers."""
    base_projection = flow._future_today_projection
    base_close = flow._close_home_precision_residual
    base_attach = flow._attach_flow_contract
    if getattr(base_projection, "_kems_flow_reserve_policy", False):
        base_projection = policy._original_future_today_projection
        base_close = policy._original_close_home_precision_residual
    if getattr(base_attach, "_kems_flow_reserve_contract_bridge", False):
        base_attach = policy._original_attach_flow_contract

    monkeypatch.setattr(flow, "_future_today_projection", base_projection)
    monkeypatch.setattr(flow, "_close_home_precision_residual", base_close)
    monkeypatch.setattr(flow, "_attach_flow_contract", base_attach)
    monkeypatch.setattr(policy, "_original_future_today_projection", None)
    monkeypatch.setattr(policy, "_original_close_home_precision_residual", None)
    monkeypatch.setattr(policy, "_original_attach_flow_contract", None)
    policy.install_flow_reserve_policy()


def _scenario():
    start = datetime(2026, 9, 10, 21, 0, tzinfo=UTC)
    end = datetime(2026, 9, 10, 21, 30, tzinfo=UTC)
    now = datetime(2026, 9, 10, 20, 59, tzinfo=UTC)
    state = {
        "today_slots": [
            {
                "valid_from": start.isoformat(),
                "valid_to": end.isoformat(),
                "rate_pence": 14.94,
                "planned_battery_to_home_kwh": 0.6,
                "rolling_planned_battery_export_kwh": 0.0,
            }
        ],
        "current_routing_snapshot": {"simulated_soc_percent": 14.5},
        "rolling_export_plan": {
            "simulated_soc_percent": 14.5,
            "hard_safety_floor_active": False,
        },
    }
    config = models.SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=15.0,
        battery_initial_percent=14.5,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
    )
    learned = models.LearnedState(typical_house_load_kw=1.2)
    forecast = models.SolarForecastState(hourly=())
    forecast_plan = models.ForecastPlanState(
        minimum_precheap_soc_percent=15.0,
        maximum_overnight_soc_percent=100.0,
    )
    tariff = tariff_module.TariffSettings(
        mode="intelligent",
        day_rate_pence=28.3036,
        offpeak_rate_pence=3.4933,
        standing_charge_pence=53.70435,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
        intelligent_slots_enabled=True,
    )
    return start, now, state, config, learned, forecast, forecast_plan, tariff


def test_build_slot_flow_remains_strict() -> None:
    """Do not hide future contract mistakes by accepting arbitrary kwargs."""
    signature = inspect.signature(slot_flow.build_slot_flow)
    assert not any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    assert "planning_target_soc_percent" not in signature.parameters


def test_real_projection_attach_builder_chain_preserves_policy_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the exact Alpha9.21 live-failing publication chain end to end."""
    _install(monkeypatch)
    start, now, state, config, learned, forecast, forecast_plan, tariff = _scenario()

    future = flow._future_today_projection(
        SimpleNamespace(),
        state,
        now=now,
        config=config,
        learned=learned,
        forecast=forecast,
        forecast_plan=forecast_plan,
        tariff=tariff,
    )
    projected = future[start.isoformat()]
    assert projected["planning_target_soc_percent"] == 15.0
    assert projected["house_import_floor_soc_percent"] == 10.0
    assert projected["hard_safety_recovery_soc_percent"] == 12.0

    # Alpha9.21 failed here because the metadata dictionary was expanded directly
    # into the strict build_slot_flow signature. Alpha9.22 must complete normally.
    flow._attach_flow_contract(state, now=now, future_today=future)

    slot = state["today_slots"][0]
    assert slot["flow_grid_import_kwh"] == pytest.approx(0.0)
    assert slot["flow_battery_to_home_kwh"] == pytest.approx(0.6)
    assert slot["flow_grid_action"] == "IDLE"
    assert slot["flow_battery_action"] == "HOME"
    assert slot["planning_target_soc_percent"] == 15.0
    assert slot["house_import_floor_soc_percent"] == 10.0
    assert slot["hard_safety_recovery_soc_percent"] == 12.0
    assert slot["planning_target_limits_export_only"] is True
    assert slot["hard_safety_floor_latched"] is False


def test_alpha922_release_scope_is_startup_presentation_only() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    source = (INTEGRATION / "agile_flow_reserve_policy.py").read_text(encoding="utf-8")

    assert manifest["version"] == "0.9.0-alpha9.26"
    reason = bundle["maintenance"]["reason"].lower()
    assert "startup hotfix" in reason
    assert "build_slot_flow" in reason
    assert "unexpected planning_target_soc_percent keyword" in reason
    assert "providers.foxess" not in source
    assert "commands_permitted = True" not in source
    assert "safe_to_write_hardware = True" not in source
