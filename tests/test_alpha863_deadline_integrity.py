"""Regression coverage for Alpha8.63 deadline / settlement integrity."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _load_deadline_guard():
    """Load deadline math with lightweight dependency stubs."""
    custom_components = sys.modules.setdefault(
        "custom_components", types.ModuleType("custom_components")
    )
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = types.ModuleType("custom_components.kems")
    package.__path__ = [str(KEMS)]
    sys.modules["custom_components.kems"] = package

    alpha717 = types.ModuleType("custom_components.kems.agile_alpha717_dispatch")
    alpha717._dispatch_targets = lambda *args, **kwargs: {}
    sys.modules[alpha717.__name__] = alpha717

    alpha731 = types.ModuleType("custom_components.kems.agile_alpha731_solar_headroom")
    alpha731._proposal_solar_evidence = lambda *args, **kwargs: {
        "available": True,
        "routed_solar_ac_kw": 0.0,
    }
    sys.modules[alpha731.__name__] = alpha731

    rolling = types.ModuleType("custom_components.kems.agile_rolling_replan")
    rolling._current_agile_soc = lambda state: float(state["soc"])
    rolling._rolling_plan = lambda *args, **kwargs: {}
    sys.modules[rolling.__name__] = rolling

    agile = types.ModuleType("custom_components.kems.agile_smart_export")
    agile._next_cheap = lambda now, tariff: tariff.deadline
    sys.modules[agile.__name__] = agile

    runtime = types.ModuleType("custom_components.kems.agile_smart_export_runtime_base")

    class Manager:
        async def async_update(self, **kwargs):
            return {}

    runtime.EfficientAgileSmartExportManager = Manager
    sys.modules[runtime.__name__] = runtime

    dispatch = types.ModuleType("custom_components.kems.agile_deadline_dispatch")
    dispatch._effective_deadline_kw = lambda config: min(
        config.max_discharge_kw,
        config.inverter_limit_kw,
    )
    dispatch._target_percent = lambda config: config.battery_reserve_percent
    sys.modules[dispatch.__name__] = dispatch

    core = types.ModuleType("custom_components.kems.kems_core")

    class SimulationConfig:
        battery_capacity_kwh = 56.42
        battery_reserve_percent = 10.0
        max_discharge_kw = 7.0
        max_charge_kw = 7.0
        inverter_limit_kw = 7.0
        export_limit_kw = 7.0
        charge_efficiency = 0.95
        discharge_efficiency = 0.95
        site_import_limit_kw = None

    core.SimulationConfig = SimulationConfig
    sys.modules[core.__name__] = core

    tariff_module = types.ModuleType("custom_components.kems.tariff")

    class TariffSettings:
        def __init__(self, deadline):
            self.deadline = deadline

    tariff_module.TariffSettings = TariffSettings
    sys.modules[tariff_module.__name__] = tariff_module

    events = types.ModuleType("custom_components.kems.agile_event_priority_runtime")
    sys.modules[events.__name__] = events

    name = "custom_components.kems.agile_deadline_guard_runtime"
    spec = importlib.util.spec_from_file_location(name, KEMS / "agile_deadline_guard_runtime.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module, SimulationConfig, TariffSettings, events


def _load_deadline_consistency():
    """Load the canonical reporting owner without Home Assistant."""
    custom_components = sys.modules.setdefault(
        "custom_components", types.ModuleType("custom_components")
    )
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = types.ModuleType("custom_components.kems")
    package.__path__ = [str(KEMS)]
    sys.modules["custom_components.kems"] = package

    continuity = types.ModuleType(
        "custom_components.kems.agile_live_solar_soc_continuity"
    )

    class Parent:
        pass

    continuity.LiveSolarSocContinuityAgileSmartExportManager = Parent
    sys.modules[continuity.__name__] = continuity

    core = types.ModuleType("custom_components.kems.kems_core")

    class SimulationConfig:
        max_discharge_kw = 7.0
        inverter_limit_kw = 7.0

    core.SimulationConfig = SimulationConfig
    sys.modules[core.__name__] = core

    name = "custom_components.kems.agile_deadline_settlement_consistency"
    spec = importlib.util.spec_from_file_location(
        name,
        KEMS / "agile_deadline_settlement_consistency.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module, SimulationConfig


def test_happy_hour_moves_deadline_guard_earlier_and_blocks_event_capacity() -> None:
    guard, SimulationConfig, TariffSettings, events = _load_deadline_guard()
    config = SimulationConfig()
    now = datetime(2026, 8, 31, 19, 30, tzinfo=UTC)
    event_start = datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
    event_end = datetime(2026, 8, 31, 21, 0, tzinfo=UTC)
    deadline = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    tariff = TariffSettings(deadline)

    events._happy_hour_event = lambda self: {
        "enabled": True,
        "source": "octopus_energy",
        "start": event_start,
        "end": event_end,
        "duration_hours": 1,
    }
    events._happy_hour_charge_target = lambda self, event, cfg: {
        "charge_target_kw": 7.0,
    }

    protected = guard._deadline_guard_context(
        object(),
        {"soc": 24.0},
        now=now,
        config=config,
        tariff=tariff,
    )

    events._happy_hour_event = lambda self: {"enabled": False}
    ordinary = guard._deadline_guard_context(
        object(),
        {"soc": 24.0},
        now=now,
        config=config,
        tariff=tariff,
    )

    assert protected["happy_hour_deadline_protected"]
    assert protected["happy_hour_discharge_blocked_hours"] == pytest.approx(1.0)
    assert protected["happy_hour_deadline_obligation_kwh"] == pytest.approx(
        7.0 * 0.95 * 0.95,
        abs=0.001,
    )
    assert protected["solar_aware_remaining_capacity_kwh"] == pytest.approx(14.0)
    assert ordinary["solar_aware_remaining_capacity_kwh"] == pytest.approx(21.0)
    assert protected["required_discharge_kwh"] > ordinary["required_discharge_kwh"]
    assert protected["latest_safe_export_start"] < ordinary["latest_safe_export_start"]
    assert protected["deadline_guard_active"]


def test_settlement_rebases_stale_day_deadline_metrics_from_current_guard() -> None:
    consistency, SimulationConfig = _load_deadline_consistency()
    state = {
        "periods": {
            "today": {
                "agile_smart_export": {
                    "ready": True,
                    "ending_soc_percent": 28.51,
                    "replay_ending_soc_percent": 37.6,
                    "deadline_required_discharge_kwh": 14.78,
                    "deadline_margin_kwh": -8.568,
                    "deadline_minimum_reachable_soc_percent": 26.0,
                }
            }
        },
        "rolling_export_plan": {
            "deadline_guard": {
                "available": True,
                "deadline": "2026-08-31T22:30:00+00:00",
                "target_soc_percent": 10.0,
                "simulated_soc_percent": 28.51,
                "required_discharge_kwh": 9.921,
                "solar_aware_remaining_capacity_kwh": 6.212,
                "solar_aware_deadline_margin_kwh": -3.709,
                "required_average_discharge_kw": 11.179,
                "minimum_reachable_soc_percent": 16.92,
                "target_physically_reachable_now": False,
                "happy_hour_deadline_protected": False,
                "happy_hour_deadline_obligation_kwh": 0.0,
            }
        },
    }

    diagnostic = consistency.rebase_day_summary_deadline_from_rolling(
        state,
        config=SimulationConfig(),
    )
    agile = state["periods"]["today"]["agile_smart_export"]

    assert diagnostic["applied"]
    assert diagnostic["soc_aligned"]
    assert agile["deadline_required_discharge_kwh"] == 9.921
    assert agile["deadline_max_remaining_discharge_kwh"] == 6.212
    assert agile["deadline_margin_kwh"] == -3.709
    assert agile["deadline_minimum_reachable_soc_percent"] == 16.92
    assert agile["deadline_status"] == "Physically unreachable"
    assert agile["deadline_soc_authority"] == "settled current-day digital-twin SOC"
    assert agile["deadline_metrics_source"] == "post-settlement rolling deadline guard"
    assert diagnostic["reporting_only"]
    assert diagnostic["hardware_writes"] == "blocked"


def test_alpha863_keeps_real_hardware_writes_blocked() -> None:
    deadline_source = (KEMS / "agile_deadline_guard_runtime.py").read_text()
    consistency_source = (
        KEMS / "agile_deadline_settlement_consistency.py"
    ).read_text()
    runtime_source = (KEMS / "agile_smart_export_runtime.py").read_text()

    assert "Weekend Happy Hour event priority blocks battery discharge" in deadline_source
    assert "happy_hour_deadline_obligation_kwh" in deadline_source
    assert "DeadlineSettlementConsistencyAgileSmartExportManager" in runtime_source
    assert "services.async_call" not in consistency_source
    assert "providers.foxess" not in consistency_source
    assert '"hardware_writes": "blocked"' in consistency_source
