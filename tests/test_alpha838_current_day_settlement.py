"""Regression coverage for Alpha8.38 current-day settled export accounting."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
LONDON = ZoneInfo("Europe/London")


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "alpha838_settlement_helper",
        INTEGRATION / "agile_current_day_settlement.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Avoid importing Home Assistant/runtime dependencies: execute only the pure
    # helper prefix before the manager subclass definition.
    source = (INTEGRATION / "agile_current_day_settlement.py").read_text()
    pure_source = source.split("\n\nclass SettledCurrentDayAgileSmartExportManager", 1)[0]
    pure_source = pure_source.replace(
        "from .agile_tomorrow_soc_handoff import TomorrowSocHandoffAgileSmartExportManager\n",
        "",
    )
    exec(compile(pure_source, str(INTEGRATION / "agile_current_day_settlement.py"), "exec"), module.__dict__)
    return module


def _state() -> dict:
    return {
        "battery_wear_assumption_pence_per_discharged_kwh": 2.0,
        "today_slots": [
            {
                "valid_from": "2026-08-28T05:00:00+00:00",
                "valid_to": "2026-08-28T05:30:00+00:00",
                "local_from": "2026-08-28T06:00:00+01:00",
                "rate_pence": 10.0,
                "grid_export_kwh": 0.0,
                "solar_export_kwh": 0.25,
                "solar_to_battery_kwh": 0.0,
                "solar_to_home_kwh": 0.1,
                "battery_to_home_kwh": 0.2,
                "battery_export_kwh": 0.0,
            },
            {
                "valid_from": "2026-08-28T05:30:00+00:00",
                "valid_to": "2026-08-28T06:00:00+00:00",
                "local_from": "2026-08-28T06:30:00+01:00",
                "rate_pence": 20.0,
                "grid_export_kwh": 0.0,
                "solar_export_kwh": 0.0,
                "solar_to_battery_kwh": 0.0,
                "solar_to_home_kwh": 0.2,
                "battery_to_home_kwh": 0.3,
                "battery_export_kwh": 0.0,
            },
            {
                "valid_from": "2026-08-28T22:00:00+00:00",
                "valid_to": "2026-08-28T22:30:00+00:00",
                "local_from": "2026-08-28T23:00:00+01:00",
                "rate_pence": 30.0,
                "grid_export_kwh": 0.0,
                "solar_export_kwh": 0.0,
                "solar_to_battery_kwh": None,
                "solar_to_home_kwh": None,
                "battery_to_home_kwh": None,
                "battery_export_kwh": 0.0,
            },
        ],
        "periods": {
            "today": {
                "key": "today",
                "label": "Today",
                "ready": True,
                "full_kems_forecast": {
                    "ready": True,
                    "economic_net_cost_pence": 140.0,
                },
                "agile_smart_export": {
                    "ready": True,
                    "energy_net_cost_pence": 153.7,
                    "economic_net_cost_pence": 154.7,
                    "import_cost_pence": 100.0,
                    "export_income_pence": 0.0,
                    "grid_import_kwh": 5.0,
                    "grid_export_kwh": 0.0,
                    "solar_export_kwh": 0.25,
                    "solar_to_battery_kwh": 0.0,
                    "solar_to_home_kwh": 0.3,
                    "battery_to_home_kwh": 0.5,
                    "battery_export_kwh": 0.0,
                    "battery_wear_cost_pence": 1.0,
                    "fixed_12p_same_dispatch_income_pence": 0.0,
                    "gain_vs_fixed_12p_same_dispatch_pence": 0.0,
                    "weighted_achieved_export_rate_pence": None,
                    "ending_soc_percent": 74.3,
                },
                "comparison": {
                    "agile_advantage_pence": -14.7,
                    "winner": "Full KEMS Forecast",
                    "winner_margin_pence": 14.7,
                },
            }
        },
    }


def _settlements() -> list[dict]:
    return [
        {
            "slot": "2026-08-28T06:00:00+01:00",
            "samples": 28,
            "basis": "digital_twin",
            "outcome": {
                "charge_kw": 0.0,
                "battery_to_home_kw": 1.0,
                "battery_export_kw": 2.0,
                "total_discharge_kw": 3.0,
            },
        },
        {
            "slot": "2026-08-28T06:30:00+01:00",
            "samples": 28,
            "basis": "digital_twin",
            "outcome": {
                "charge_kw": 0.0,
                "battery_to_home_kw": 0.5,
                "battery_export_kw": 4.0,
                "total_discharge_kw": 4.5,
            },
        },
        {
            "slot": "2026-08-27T23:30:00+01:00",
            "samples": 28,
            "basis": "digital_twin",
            "outcome": {
                "charge_kw": 7.0,
                "battery_to_home_kw": 0.0,
                "battery_export_kw": 0.0,
                "total_discharge_kw": 0.0,
            },
        },
    ]


def test_settled_shadow_export_replaces_stale_zero_daily_totals() -> None:
    helper = _load_helper()
    state = _state()
    result = helper.reconcile_current_day_settlements(
        state,
        _settlements(),
        datetime(2026, 8, 28, 8, 50, tzinfo=LONDON),
    )

    assert result["applied"] is True
    assert result["settled_slots_applied"] == 2
    agile = state["periods"]["today"]["agile_smart_export"]
    # 06:00: 1.0 kWh battery export + 0.25 kWh solar export.
    # 06:30: 2.0 kWh battery export. Total grid export = 3.25 kWh.
    assert agile["grid_export_kwh"] == 3.25
    assert agile["battery_export_kwh"] == 3.0
    assert agile["battery_to_home_kwh"] == 0.75
    assert agile["export_income_pence"] == 52.5
    assert agile["fixed_12p_same_dispatch_income_pence"] == 39.0
    assert agile["gain_vs_fixed_12p_same_dispatch_pence"] == 13.5
    assert agile["weighted_achieved_export_rate_pence"] == 16.1538

    # Preserve import accounting, recover the standing component, then settle
    # export income and battery wear into the canonical daily economics.
    assert agile["grid_import_kwh"] == 5.0
    assert agile["import_cost_pence"] == 100.0
    assert agile["energy_net_cost_pence"] == 101.2
    assert agile["battery_wear_cost_pence"] == 7.5
    assert agile["economic_net_cost_pence"] == 108.7

    comparison = state["periods"]["today"]["comparison"]
    assert comparison["agile_advantage_pence"] == 31.3
    assert comparison["winner"] == "Agile Smart Export"
    assert comparison["winner_margin_pence"] == 31.3


def test_settlement_is_idempotent_and_leaves_future_slots_unplanned() -> None:
    helper = _load_helper()
    state = _state()
    now = datetime(2026, 8, 28, 8, 50, tzinfo=LONDON)
    first = helper.reconcile_current_day_settlements(state, _settlements(), now)
    snapshot = json.dumps(state, sort_keys=True)
    second = helper.reconcile_current_day_settlements(state, _settlements(), now)

    assert first["grid_export_kwh"] == second["grid_export_kwh"] == 3.25
    assert json.dumps(state, sort_keys=True) == snapshot
    future = state["today_slots"][2]
    assert future["local_from"] == "2026-08-28T23:00:00+01:00"
    assert future["battery_to_home_kwh"] is None
    assert future["battery_export_kwh"] == 0.0
    assert "settlement_source" not in future


def test_only_same_local_day_digital_twin_outcomes_are_used() -> None:
    helper = _load_helper()
    state = _state()
    wrong = _settlements()[2:]
    result = helper.reconcile_current_day_settlements(
        state,
        wrong,
        datetime(2026, 8, 28, 8, 50, tzinfo=LONDON),
    )
    assert result["applied"] is False
    assert state["periods"]["today"]["agile_smart_export"]["grid_export_kwh"] == 0.0


def test_runtime_join_runs_after_shadow_settlement_without_hardware_writes() -> None:
    runtime = (INTEGRATION / "agile_smart_export_runtime.py").read_text()
    coordinator = (INTEGRATION / "coordinator.py").read_text()
    helper_source = (INTEGRATION / "agile_current_day_settlement.py").read_text()

    assert "SettledCurrentDayAgileSmartExportManager" in runtime
    assert "reconcile_current_day_settlements" in coordinator
    assert coordinator.index("await self._shadow_validation.async_update(") < coordinator.index(
        "reconcile_current_day_settlements"
    )
    assert ".services.async_call(" not in helper_source
    assert "providers.foxess" not in helper_source
    assert '"hardware_writes": "blocked"' in helper_source


def test_alpha838_version_and_release_scope() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    assert manifest["version"] == "0.8.0-alpha8.38"
    assert bundle["maintenance"]["affected_components"] == [
        "kems_core",
        "dashboard",
    ]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.4"
