"""Regression proof for Alpha9.21+ planning-target / house-floor separation."""

from __future__ import annotations

import importlib
import json
import sys
import types
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def _load_projection_modules():
    """Load the real projection with the suite's established tiny HA stubs."""
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
        """Enough generic-looking Store API for module import."""

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
    core_models = importlib.import_module("custom_components.kems.kems_core")
    tariff_module = importlib.import_module("custom_components.kems.tariff")
    return flow, policy, core_models, tariff_module


flow, policy, core_models, tariff_module = _load_projection_modules()
ForecastPlanState = core_models.ForecastPlanState
LearnedState = core_models.LearnedState
SimulationConfig = core_models.SimulationConfig
SolarForecastState = core_models.SolarForecastState
TariffSettings = tariff_module.TariffSettings


def _install_production_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the current reserve policy over canonical helpers without leaks."""
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

    assert (
        flow._future_today_projection
        is policy._future_today_projection_with_separate_reserves
    )
    assert flow._close_home_precision_residual is policy._house_floor_close
    assert (
        flow._attach_flow_contract is policy._attach_flow_contract_with_policy_metadata
    )


def _project(
    *,
    soc_percent: float,
    planned_export_kwh: float = 0.0,
    hard_floor_latched: bool = False,
    forecast_floor_percent: float = 15.0,
    solar_net_house_protection: dict[str, object] | None = None,
) -> dict[str, object]:
    """Run the real future-flow projection for one pre-cheap half hour."""
    start = datetime(2026, 9, 10, 21, 0, tzinfo=UTC)  # 22:00 BST
    end = datetime(2026, 9, 10, 21, 30, tzinfo=UTC)
    now = datetime(2026, 9, 10, 20, 59, tzinfo=UTC)
    state = {
        "today_slots": [
            {
                "valid_from": start.isoformat(),
                "valid_to": end.isoformat(),
                "rate_pence": 14.94,
                "planned_battery_to_home_kwh": 0.6,
                "rolling_planned_battery_export_kwh": planned_export_kwh,
            }
        ],
        "current_routing_snapshot": {"simulated_soc_percent": soc_percent},
        "rolling_export_plan": {
            "simulated_soc_percent": soc_percent,
            "hard_safety_floor_active": hard_floor_latched,
        },
    }
    config = SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=15.0,
        battery_initial_percent=soc_percent,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
    )
    learned = LearnedState(typical_house_load_kw=1.2)
    forecast = SolarForecastState(hourly=())
    forecast_plan = ForecastPlanState(
        minimum_precheap_soc_percent=forecast_floor_percent,
        maximum_overnight_soc_percent=100.0,
    )
    tariff = TariffSettings(
        mode="intelligent",
        day_rate_pence=28.3036,
        offpeak_rate_pence=3.4933,
        standing_charge_pence=53.70435,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
        intelligent_slots_enabled=True,
    )

    projection = flow._future_today_projection(
        SimpleNamespace(_kems_solar_net_house_protection=solar_net_house_protection),
        state,
        now=now,
        config=config,
        learned=learned,
        forecast=forecast,
        forecast_plan=forecast_plan,
        tariff=tariff,
    )
    return projection[start.isoformat()]


def test_precheap_house_service_may_cross_15_without_expensive_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """15% stops export; it must not make Grid serve ordinary house demand."""
    _install_production_projection(monkeypatch)

    row = _project(soc_percent=14.5)

    assert row["battery_to_home_kwh"] == pytest.approx(0.6)
    assert row["grid_import_kwh"] == pytest.approx(0.0)
    assert 10.0 < row["estimated_soc_percent"] < 15.0
    assert row["planning_target_soc_percent"] == 15.0
    assert row["house_import_floor_soc_percent"] == 10.0
    assert row["hard_safety_recovery_soc_percent"] == 12.0
    assert row["planning_target_limits_export_only"] is True


def test_house_demand_crosses_15_before_any_deliberate_export(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """House-first discharge may cross 15%, but deliberate export may not."""
    _install_production_projection(monkeypatch)

    row = _project(soc_percent=16.0, planned_export_kwh=3.0)

    assert row["battery_to_home_kwh"] == pytest.approx(0.6)
    assert row["battery_export_kwh"] == pytest.approx(0.0)
    assert row["grid_import_kwh"] == pytest.approx(0.0)
    assert 10.0 < row["estimated_soc_percent"] < 15.0


def test_configured_15_target_limits_export_even_if_incoming_forecast_floor_is_lower(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduce Alpha9.22 live leak: display export must never inherit 10%."""
    _install_production_projection(monkeypatch)

    row = _project(
        soc_percent=20.0,
        planned_export_kwh=3.0,
        forecast_floor_percent=10.0,
    )

    assert row["battery_to_home_kwh"] == pytest.approx(0.6)
    assert 0.0 < row["battery_export_kwh"] < 3.0
    assert row["grid_import_kwh"] == pytest.approx(0.0)
    assert row["estimated_soc_percent"] == pytest.approx(15.0)
    assert row["planning_target_soc_percent"] == 15.0
    assert row["house_import_floor_soc_percent"] == 10.0
    assert row["planning_target_limits_export_only"] is True


def test_absolute_10_percent_floor_allows_grid_to_serve_house(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At the hard floor, battery-to-home stops and Grid may serve the house."""
    _install_production_projection(monkeypatch)

    row = _project(soc_percent=10.0)

    assert row["battery_to_home_kwh"] == pytest.approx(0.0)
    assert row["grid_import_kwh"] == pytest.approx(0.6)
    assert row["estimated_soc_percent"] == pytest.approx(10.0)


def test_12_percent_recovery_latch_remains_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted hard-floor latch suppresses discharge until recovery."""
    _install_production_projection(monkeypatch)

    row = _project(soc_percent=11.0, hard_floor_latched=True)

    assert row["hard_safety_floor_latched"] is True
    assert row["battery_to_home_kwh"] == pytest.approx(0.0)
    assert row["battery_export_kwh"] == pytest.approx(0.0)
    assert row["grid_import_kwh"] == pytest.approx(0.6)
    assert row["estimated_soc_percent"] == pytest.approx(11.0)


def test_alpha923_release_scope_is_projection_only() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    source = (INTEGRATION / "agile_flow_reserve_policy.py").read_text(encoding="utf-8")

    assert manifest["version"] == "0.9.0-alpha9.199"
    reason = bundle["maintenance"]["reason"].lower()
    assert "export-floor correction" in reason
    assert "15% planning/export target" in reason
    assert "10% absolute floor" in reason
    assert "12% recovery latch" in reason
    assert "providers.foxess" not in source
    assert "commands_permitted = True" not in source
    assert "safe_to_write_hardware = True" not in source


def test_rejected_low_confidence_solar_net_house_zero_does_not_erase_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduce 10 Nov 22:50: inactive 0kW sentinel + learned 1.2kW."""
    _install_production_projection(monkeypatch)

    row = _project(
        soc_percent=14.5,
        solar_net_house_protection={
            "active": False,
            "conservative_house_kw": 0.0,
            "gross_house_kwh": 0.746,
            "net_house_kwh": 0.746,
            "confidence_percent": 55.0,
            "reason": "solar forecast confidence below safe credit threshold",
        },
    )

    assert row["battery_to_home_kwh"] == pytest.approx(0.6)
    assert row["battery_export_kwh"] == pytest.approx(0.0)
    assert row["grid_import_kwh"] == pytest.approx(0.0)
    assert 10.0 < row["estimated_soc_percent"] < 14.5
    assert row["planning_target_soc_percent"] == 15.0
    assert row["house_import_floor_soc_percent"] == 10.0
    assert row["planning_target_limits_export_only"] is True


def test_active_valid_solar_net_house_override_remains_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use a genuinely active 0.4kW net-house estimate, not the learned 1.2kW."""
    _install_production_projection(monkeypatch)

    row = _project(
        soc_percent=14.5,
        solar_net_house_protection={
            "active": True,
            "conservative_house_kw": 0.4,
            "confidence_percent": 95.0,
        },
    )

    assert row["battery_to_home_kwh"] == pytest.approx(0.2)
    assert row["grid_import_kwh"] == pytest.approx(0.0)
    assert row["battery_export_kwh"] == pytest.approx(0.0)


def test_nonfinite_or_inactive_nonzero_house_override_falls_back_to_learned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rejected proposals and NaN cannot erase or invent house demand."""
    _install_production_projection(monkeypatch)

    for evidence in (
        {"active": False, "conservative_house_kw": 0.7},
        {"active": True, "conservative_house_kw": float("nan")},
        {"conservative_house_kw": 0.0},
    ):
        row = _project(
            soc_percent=14.5,
            solar_net_house_protection=evidence,
        )
        assert row["battery_to_home_kwh"] == pytest.approx(0.6)
        assert row["grid_import_kwh"] == pytest.approx(0.0)


def test_at_hard_house_floor_inactive_solar_estimate_cannot_force_discharge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The existing 10% stop and 12% latch still outrank forecast fallback."""
    _install_production_projection(monkeypatch)
    evidence = {"active": False, "conservative_house_kw": 0.0}
    for soc, latched in ((10.0, False), (11.0, True)):
        row = _project(
            soc_percent=soc,
            hard_floor_latched=latched,
            solar_net_house_protection=evidence,
        )
        assert row["battery_to_home_kwh"] == pytest.approx(0.0)
        assert row["grid_import_kwh"] == pytest.approx(0.6)
        assert row["battery_export_kwh"] == pytest.approx(0.0)


def test_nov10_2250_future_2300_house_flow_and_2330_cheap_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact live failure: active precheap + future house slot + cheap slot."""
    _install_production_projection(monkeypatch)

    start_current = datetime(2026, 11, 10, 22, 30, tzinfo=UTC)
    start_future = datetime(2026, 11, 10, 23, 0, tzinfo=UTC)
    start_cheap = datetime(2026, 11, 10, 23, 30, tzinfo=UTC)
    now = datetime(2026, 11, 10, 22, 50, tzinfo=UTC)
    slots = [
        {
            "valid_from": start.isoformat(),
            "valid_to": (start + timedelta(minutes=30)).isoformat(),
            "rate_pence": rate,
            "planned_battery_to_home_kwh": 0.0,
            "rolling_planned_battery_export_kwh": 0.0,
        }
        for start, rate in (
            (start_current, 16.7),
            (start_future, 16.18),
            (start_cheap, 16.18),
        )
    ]
    state = {
        "today_slots": slots,
        "current_routing_snapshot": {"simulated_soc_percent": 14.724},
        "rolling_export_plan": {
            "simulated_soc_percent": 14.724,
            "hard_safety_floor_active": False,
        },
    }
    config = SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=15.0,
        battery_initial_percent=14.724,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
    )
    tariff = TariffSettings(
        mode="intelligent",
        day_rate_pence=35.8828,
        offpeak_rate_pence=6.6,
        standing_charge_pence=55.52,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
        intelligent_slots_enabled=True,
    )
    projected = flow._future_today_projection(
        SimpleNamespace(
            _kems_solar_net_house_protection={
                "active": False,
                "conservative_house_kw": 0.0,
                "gross_house_kwh": 0.746,
                "net_house_kwh": 0.746,
                "confidence_percent": 55.0,
            }
        ),
        state,
        now=now,
        config=config,
        learned=LearnedState(typical_house_load_kw=0.994),
        forecast=SolarForecastState(hourly=()),
        forecast_plan=ForecastPlanState(
            minimum_precheap_soc_percent=15.0,
            maximum_overnight_soc_percent=85.7,
        ),
        tariff=tariff,
    )
    current = projected[start_current.isoformat()]
    future = projected[start_future.isoformat()]
    cheap = projected[start_cheap.isoformat()]
    assert 0.0 < current["battery_to_home_kwh"] < 0.2
    assert future["battery_to_home_kwh"] == pytest.approx(0.497)
    assert future["grid_import_kwh"] == pytest.approx(0.0)
    assert future["battery_export_kwh"] == pytest.approx(0.0)
    assert 10.0 < future["estimated_soc_percent"] < current["estimated_soc_percent"]
    assert future["house_import_floor_soc_percent"] == 10.0
    assert future["planning_target_soc_percent"] == 15.0
    assert cheap["battery_to_home_kwh"] == pytest.approx(0.0)
    assert cheap["grid_to_battery_kwh"] > 0.0
    assert cheap["grid_import_kwh"] > 0.497
