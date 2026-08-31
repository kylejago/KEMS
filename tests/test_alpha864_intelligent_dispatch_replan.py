"""Regression coverage for Alpha8.64 Intelligent dispatch replanning."""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
LONDON = ZoneInfo("Europe/London")


def _load_module():
    """Load the canonical Alpha8.64 module without Home Assistant."""
    custom_components = sys.modules.setdefault(
        "custom_components", types.ModuleType("custom_components")
    )
    custom_components.__path__ = [str(ROOT / "custom_components")]
    package = types.ModuleType("custom_components.kems")
    package.__path__ = [str(KEMS)]
    sys.modules["custom_components.kems"] = package

    routing = types.ModuleType("custom_components.kems.agile_alpha730_current_routing")

    def current_slot(state, now):
        for slot in state.get("today_slots", []):
            if slot.get("active"):
                return slot
        return None

    routing._current_slot = current_slot
    routing._current_simulation = lambda self, now: (
        getattr(self, "_alpha864_current_snapshot", None),
        getattr(self, "_rolling_config", None),
        getattr(self, "_test_simulation", None),
    )
    sys.modules[routing.__name__] = routing

    rolling = types.ModuleType("custom_components.kems.agile_rolling_replan")

    def rolling_plan(self, state, *, now, config, tariff):
        self._test_seen_slots = list(state.get("today_slots", []))
        return {
            "available": True,
            "simulated_soc_percent": 55.0,
            "planned_battery_export_kwh": 4.0,
            "selected_slots": [
                {
                    "label": slot.get("label"),
                    "valid_from": slot.get("valid_from"),
                    "planned_battery_export_kwh": 2.0,
                }
                for slot in state.get("today_slots", [])
            ],
        }

    rolling._rolling_plan = rolling_plan
    sys.modules[rolling.__name__] = rolling

    settlement = types.ModuleType(
        "custom_components.kems.agile_deadline_settlement_consistency"
    )

    class Parent:
        def _publish(self, state):
            self._parent_publish_calls = getattr(self, "_parent_publish_calls", 0) + 1

        async def async_update(self, **kwargs):
            self._rolling_now = kwargs["now"]
            self._rolling_config = kwargs["config"]
            self._rolling_tariff = kwargs["tariff"]
            self._state = {
                "rolling_export_plan": {
                    "available": True,
                    "simulated_soc_percent": 61.0,
                    "planned_battery_export_kwh": 3.0,
                    "selected_slots": [],
                },
                "today_slots": [],
            }
            self._publish(self._state)
            return self._state

    settlement.DeadlineSettlementConsistencyAgileSmartExportManager = Parent
    sys.modules[settlement.__name__] = settlement

    core = types.ModuleType("custom_components.kems.kems_core")

    class SimulationConfig:
        battery_capacity_kwh = 56.42
        battery_reserve_percent = 10.0
        max_charge_kw = 7.0
        max_discharge_kw = 7.0
        inverter_limit_kw = 7.0
        export_limit_kw = 7.0
        charge_efficiency = 0.95
        discharge_efficiency = 0.95
        site_import_limit_kw = None

    class Snapshot:
        pass

    core.SimulationConfig = SimulationConfig
    core.Snapshot = Snapshot
    sys.modules[core.__name__] = core

    tariff_module = types.ModuleType("custom_components.kems.tariff")

    class TariffSettings:
        offpeak_start = time(23, 30)
        offpeak_end = time(5, 30)

    def manual_schedule(now, start, end):
        local = now.astimezone(LONDON).timetz().replace(tzinfo=None)
        cheap = local >= start or local < end
        return cheap, None, None

    tariff_module.TariffSettings = TariffSettings
    tariff_module.manual_schedule = manual_schedule
    sys.modules[tariff_module.__name__] = tariff_module

    name = "custom_components.kems.agile_intelligent_dispatch_replan"
    spec = importlib.util.spec_from_file_location(
        name,
        KEMS / "agile_intelligent_dispatch_replan.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module, SimulationConfig, Snapshot, TariffSettings, rolling


def _snapshot(Snapshot, *, charging=True, confirmed=True):
    snapshot = Snapshot()
    snapshot.intelligent_slot = True
    snapshot.intelligent_slot_confirmation = "confirmed" if confirmed else "blocked"
    snapshot.intelligent_slot_evidence = {
        "confirmed": confirmed,
        "large_import_permitted": confirmed,
    }
    snapshot.tariff_stale_fields = ()
    snapshot.ev_charging = charging
    snapshot.house_load_kw = 0.8
    return snapshot


def test_daytime_confirmed_intelligent_dispatch_is_authoritative() -> None:
    module, _, Snapshot, TariffSettings, _ = _load_module()
    snapshot = _snapshot(Snapshot)

    assert module._confirmed_intelligent_dispatch(
        snapshot,
        now=datetime(2026, 8, 31, 21, 0, tzinfo=LONDON),
        tariff=TariffSettings(),
    )


def test_confirmation_fails_closed_without_ohme_charging() -> None:
    module, _, Snapshot, TariffSettings, _ = _load_module()
    snapshot = _snapshot(Snapshot, charging=False)

    assert not module._confirmed_intelligent_dispatch(
        snapshot,
        now=datetime(2026, 8, 31, 21, 0, tzinfo=LONDON),
        tariff=TariffSettings(),
    )


def test_normal_overnight_window_is_left_to_existing_handover() -> None:
    module, _, Snapshot, TariffSettings, _ = _load_module()
    snapshot = _snapshot(Snapshot)

    assert not module._confirmed_intelligent_dispatch(
        snapshot,
        now=datetime(2026, 8, 31, 23, 45, tzinfo=LONDON),
        tariff=TariffSettings(),
    )


def test_confirmed_dispatch_slot_is_removed_before_rolling_replan() -> None:
    module, SimulationConfig, Snapshot, TariffSettings, rolling = _load_module()
    module.install_intelligent_dispatch_replan()
    manager = types.SimpleNamespace(
        _alpha864_current_snapshot=_snapshot(Snapshot),
        _alpha864_transition="confirmed_start",
    )
    active = {"label": "21:00", "valid_from": "active", "active": True}
    future = {"label": "21:30", "valid_from": "future", "active": False}
    state = {"today_slots": [active, future]}

    plan = rolling._rolling_plan(
        manager,
        state,
        now=datetime(2026, 8, 31, 21, 0, tzinfo=LONDON),
        config=SimulationConfig(),
        tariff=TariffSettings(),
    )

    assert manager._test_seen_slots == [future]
    assert plan["intelligent_dispatch_slot_excluded_from_export_plan"] is True
    assert plan["intelligent_dispatch_replan_reason"] == "confirmed_start"
    assert plan["intelligent_dispatch_slot"]["label"] == "21:00"


def test_confirmed_dispatch_handover_blocks_stale_discharge_and_exports() -> None:
    module, SimulationConfig, Snapshot, _, _ = _load_module()

    class States:
        @staticmethod
        def get(entity_id):
            return None

    manager = types.SimpleNamespace(
        _alpha864_current_snapshot=_snapshot(Snapshot),
        _rolling_config=SimulationConfig(),
        _hass=types.SimpleNamespace(states=States()),
        _test_simulation=types.SimpleNamespace(
            current_simulated_house_load_kw=0.8,
            current_simulated_solar_power_kw=0.5,
            current_simulated_grid_import_kw=7.8,
            current_simulated_grid_export_kw=0.1,
            current_simulated_solar_to_battery_power_kw=0.4,
            current_simulated_battery_charge_power_kw=7.0,
            current_simulated_total_kh7_output_kw=0.1,
            current_simulated_total_site_import_kw=7.8,
            simulated_battery_soc=52.0,
        ),
        _set=lambda *args, **kwargs: None,
    )
    active = {
        "label": "21:00",
        "valid_from": "2026-08-31T20:00:00+00:00",
        "valid_to": "2026-08-31T20:30:00+00:00",
        "active": True,
        "rolling_planned_battery_export_kwh": 3.0,
        "rolling_target_battery_export_kw": 6.0,
        "rolling_target_total_discharge_kw": 7.0,
    }
    state = {
        "today_slots": [active],
        "rolling_export_plan": {
            "available": True,
            "current_house_battery_kw": 1.0,
            "current_battery_export_target_kw": 6.0,
            "current_battery_discharge_target_kw": 7.0,
            "selected_slots": [],
        },
    }

    snapshot = module._apply_intelligent_dispatch_handover(
        manager,
        state,
        now=datetime(2026, 8, 31, 21, 0, tzinfo=LONDON),
    )

    assert snapshot is not None
    assert snapshot["dispatch_mode"] == "cheap_charge"
    assert snapshot["battery_to_home_kw"] == 0.0
    assert snapshot["battery_export_kw"] == 0.0
    assert snapshot["total_discharge_kw"] == 0.0
    assert snapshot["grid_to_battery_kw"] == 6.6
    assert state["rolling_export_plan"]["dispatch_mode"] == "cheap_charge"
    assert state["rolling_export_plan"]["current_house_battery_kw"] == 0.0
    assert state["rolling_export_plan"]["current_battery_export_target_kw"] == 0.0
    assert state["rolling_export_plan"]["current_battery_discharge_target_kw"] == 0.0
    assert state["rolling_export_plan"]["current_battery_charge_target_kw"] == 7.0
    assert active["rolling_planned_battery_export_kwh"] == 0.0
    assert active["rolling_target_battery_export_kw"] == 0.0
    assert active["rolling_target_total_discharge_kw"] == 0.0


def test_start_and_end_transitions_are_explicit() -> None:
    module, SimulationConfig, Snapshot, TariffSettings, _ = _load_module()
    manager = module.IntelligentDispatchReplanAgileSmartExportManager()
    manager._hass = types.SimpleNamespace(states=types.SimpleNamespace(get=lambda _: None))
    manager._set = lambda *args, **kwargs: None
    manager._test_simulation = types.SimpleNamespace(
        current_simulated_house_load_kw=0.8,
        current_simulated_solar_power_kw=0.0,
        current_simulated_grid_import_kw=7.8,
        current_simulated_grid_export_kw=0.0,
        current_simulated_solar_to_battery_power_kw=0.0,
        current_simulated_battery_charge_power_kw=7.0,
        current_simulated_total_kh7_output_kw=0.0,
        current_simulated_total_site_import_kw=7.8,
        simulated_battery_soc=61.0,
    )
    now = datetime(2026, 8, 31, 21, 0, tzinfo=LONDON)

    import asyncio

    asyncio.run(
        manager.async_update(
            records=[_snapshot(Snapshot)],
            now=now,
            config=SimulationConfig(),
            learned=object(),
            forecast=object(),
            forecast_plan=object(),
            tariff=TariffSettings(),
        )
    )
    assert manager._state["intelligent_dispatch_replan"]["transition"] == (
        "confirmed_start"
    )
    assert manager._state["intelligent_dispatch_replan"]["plan_invalidated"] is True

    ended = _snapshot(Snapshot, charging=False)
    asyncio.run(
        manager.async_update(
            records=[ended],
            now=datetime(2026, 8, 31, 21, 31, tzinfo=LONDON),
            config=SimulationConfig(),
            learned=object(),
            forecast=object(),
            forecast_plan=object(),
            tariff=TariffSettings(),
        )
    )
    assert manager._state["intelligent_dispatch_replan"]["transition"] == "confirmed_end"
    assert manager._state["intelligent_dispatch_replan"]["plan_invalidated"] is True
    assert manager._state["intelligent_dispatch_replan"]["active"] is False
