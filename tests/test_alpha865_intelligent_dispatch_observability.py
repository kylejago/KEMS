"""Regression coverage for Alpha8.65 Intelligent dispatch observability."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"


def _load_alpha864_helper():
    name = "alpha864_test_helper"
    spec = importlib.util.spec_from_file_location(
        name,
        ROOT / "tests" / "test_alpha864_intelligent_dispatch_replan.py",
    )
    assert spec is not None and spec.loader is not None
    helper = importlib.util.module_from_spec(spec)
    sys.modules[name] = helper
    spec.loader.exec_module(helper)
    return helper


def _load_observability_module():
    name = "custom_components.kems.agile_intelligent_dispatch_observability"
    spec = importlib.util.spec_from_file_location(
        name,
        KEMS / "agile_intelligent_dispatch_observability.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _manager_fixture():
    helper = _load_alpha864_helper()
    _, SimulationConfig, Snapshot, TariffSettings, _ = helper._load_module()
    module = _load_observability_module()

    manager = module.IntelligentDispatchObservabilityAgileSmartExportManager()
    manager._hass = types.SimpleNamespace(
        states=types.SimpleNamespace(get=lambda _: None)
    )
    manager._published = []
    manager._set = lambda *args, **kwargs: manager._published.append((args, kwargs))
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
    return helper, manager, SimulationConfig, Snapshot, TariffSettings


def _update(
    helper,
    manager,
    SimulationConfig,
    Snapshot,
    TariffSettings,
    *,
    now,
    charging,
):
    return asyncio.run(
        manager.async_update(
            records=[helper._snapshot(Snapshot, charging=charging)],
            now=now,
            config=SimulationConfig(),
            learned=object(),
            forecast=object(),
            forecast_plan=object(),
            tariff=TariffSettings(),
        )
    )


def test_start_evidence_survives_later_confirmed_active_scan() -> None:
    helper, manager, SimulationConfig, Snapshot, TariffSettings = _manager_fixture()
    london = helper.LONDON

    _update(
        helper,
        manager,
        SimulationConfig,
        Snapshot,
        TariffSettings,
        now=datetime(2026, 9, 1, 21, 0, tzinfo=london),
        charging=True,
    )
    started = dict(manager._state["intelligent_dispatch_replan"])
    assert started["transition"] == "confirmed_start"
    assert started["last_transition"] == "confirmed_start"
    assert started["last_confirmed_start"]["plan_invalidated"] is True
    assert started["last_confirmed_start"]["current_slot_export_blocked"] is True
    start_at = started["last_transition_at"]

    _update(
        helper,
        manager,
        SimulationConfig,
        Snapshot,
        TariffSettings,
        now=datetime(2026, 9, 1, 21, 5, tzinfo=london),
        charging=True,
    )
    active = manager._state["intelligent_dispatch_replan"]
    assert active["transition"] == "confirmed_active"
    assert active["last_transition"] == "confirmed_start"
    assert active["last_transition_at"] == start_at
    assert active["last_confirmed_start"]["occurred_at"] == start_at
    assert active["last_confirmed_end"] is None
    assert [item["transition"] for item in active["transition_history"]] == [
        "confirmed_start"
    ]


def test_end_evidence_and_start_evidence_survive_later_inactive_scan() -> None:
    helper, manager, SimulationConfig, Snapshot, TariffSettings = _manager_fixture()
    london = helper.LONDON

    _update(
        helper,
        manager,
        SimulationConfig,
        Snapshot,
        TariffSettings,
        now=datetime(2026, 9, 1, 21, 0, tzinfo=london),
        charging=True,
    )
    start_at = manager._state["intelligent_dispatch_replan"]["last_transition_at"]

    _update(
        helper,
        manager,
        SimulationConfig,
        Snapshot,
        TariffSettings,
        now=datetime(2026, 9, 1, 21, 31, tzinfo=london),
        charging=False,
    )
    ended = manager._state["intelligent_dispatch_replan"]
    assert ended["transition"] == "confirmed_end"
    assert ended["last_transition"] == "confirmed_end"
    assert ended["last_confirmed_start"]["occurred_at"] == start_at
    assert ended["last_confirmed_end"]["plan_invalidated"] is True
    assert ended["last_confirmed_end"]["current_slot_export_blocked"] is False
    end_at = ended["last_transition_at"]

    _update(
        helper,
        manager,
        SimulationConfig,
        Snapshot,
        TariffSettings,
        now=datetime(2026, 9, 1, 21, 35, tzinfo=london),
        charging=False,
    )
    inactive = manager._state["intelligent_dispatch_replan"]
    assert inactive["transition"] == "inactive"
    assert inactive["last_transition"] == "confirmed_end"
    assert inactive["last_transition_at"] == end_at
    assert inactive["last_confirmed_start"]["occurred_at"] == start_at
    assert inactive["last_confirmed_end"]["occurred_at"] == end_at
    assert [item["transition"] for item in inactive["transition_history"]] == [
        "confirmed_start",
        "confirmed_end",
    ]
    assert inactive["retention_scope"] == "manager lifetime"
    assert inactive["hardware_writes"] == "blocked"


def test_alpha865_is_observability_only_successor() -> None:
    runtime = (KEMS / "agile_smart_export_runtime.py").read_text(encoding="utf-8")
    manifest = json.loads((KEMS / "manifest.json").read_text(encoding="utf-8"))
    bundle = json.loads(
        (ROOT / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    alpha864 = (KEMS / "agile_intelligent_dispatch_replan.py").read_text(
        encoding="utf-8"
    )

    assert (
        "EfficientAgileSmartExportManager = "
        "IntelligentDispatchObservabilityAgileSmartExportManager"
    ) in runtime
    assert manifest["version"] == "0.8.0-alpha8.65"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.9"
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert "Alpha8.64 keeps the frozen Alpha7 boundary intact" in alpha864
    assert "hardware writes" in alpha864
