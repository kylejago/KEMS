"""Regression coverage for settled current-day Agile accounting."""

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
        "alpha839_settlement_helper",
        INTEGRATION / "agile_current_day_settlement.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    source = (INTEGRATION / "agile_current_day_settlement.py").read_text()
    pure_source = source.split(
        "\n\nclass SettledCurrentDayAgileSmartExportManager",
        1,
    )[0]
    handoff_import = (
        "from .agile_tomorrow_soc_handoff import "
        "TomorrowSocHandoffAgileSmartExportManager\n"
    )
    pure_source = pure_source.replace(handoff_import, "")
    exec(
        compile(
            pure_source,
            str(INTEGRATION / "agile_current_day_settlement.py"),
            "exec",
        ),
        module.__dict__,
    )
    return module


def _state() -> dict:
    return {
        "battery_wear_assumption_pence_per_discharged_kwh": 2.0,
        "current_routing_snapshot": {
            "available": True,
            "simulated_soc_percent": 74.3,
        },
        "today_slots": [
            {
                "valid_from": "2026-08-28T05:00:00+00:00",
                "valid_to": "2026-08-28T05:30:00+00:00",
                "local_from": "2026-08-28T06:00:00+01:00",
                "rate_pence": 10.0,
                "grid_export_kwh": 0.25,
                "solar_export_kwh": 0.25,
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
                "battery_to_home_kwh": 0.3,
                "battery_export_kwh": 0.0,
            },
            {
                "valid_from": "2026-08-28T22:00:00+00:00",
                "valid_to": "2026-08-28T22:30:00+00:00",
                "local_from": "2026-08-28T23:00:00+01:00",
                "rate_pence": 30.0,
                "grid_export_kwh": 9.0,
                "solar_export_kwh": 0.0,
                "battery_to_home_kwh": None,
                "battery_export_kwh": 9.0,
                "rolling_planned_battery_export_kwh": 9.0,
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
                    "grid_export_kwh": 9.25,
                    "solar_export_kwh": 0.25,
                    "battery_to_home_kwh": 0.5,
                    "battery_export_kwh": 9.0,
                    "battery_wear_cost_pence": 19.0,
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


def _reconcile(state: dict) -> dict:
    helper = _load_helper()
    return helper.reconcile_current_day_settlements(
        state,
        _settlements(),
        datetime(2026, 8, 28, 8, 50, tzinfo=LONDON),
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )


def test_alpha839_settles_export_without_counting_future_plan() -> None:
    state = _state()
    result = _reconcile(state)

    assert result["applied"] is True
    assert result["settled_slots_applied"] == 2
    assert result["completed_slots_accounted"] == 2

    agile = state["periods"]["today"]["agile_smart_export"]
    assert agile["grid_export_kwh"] == 3.25
    assert agile["solar_export_kwh"] == 0.25
    assert agile["battery_export_kwh"] == 3.0
    assert agile["export_income_pence"] == 52.5
    assert agile["fixed_12p_same_dispatch_income_pence"] == 39.0
    assert agile["gain_vs_fixed_12p_same_dispatch_pence"] == 13.5
    assert agile["weighted_achieved_export_rate_pence"] == 16.1538

    future = state["today_slots"][2]
    assert future["battery_export_kwh"] == 9.0
    assert future["rolling_planned_battery_export_kwh"] == 9.0
    assert "settlement_source" not in future


def test_alpha839_preserves_replay_battery_home_and_rebuilds_economics() -> None:
    state = _state()
    result = _reconcile(state)
    agile = state["periods"]["today"]["agile_smart_export"]

    assert agile["battery_to_home_kwh"] == 0.5
    assert agile["replay_battery_to_home_kwh"] == 0.5
    assert agile["battery_to_home_accounting_source"] == "existing Agile day replay"

    assert agile["grid_import_kwh"] == 5.0
    assert agile["import_cost_pence"] == 100.0
    assert agile["energy_net_cost_pence"] == 101.2
    assert agile["battery_wear_cost_pence"] == 7.0
    assert agile["economic_net_cost_pence"] == 108.2

    assert result["all_accounting_checks_passed"] is True
    assert all(result["accounting_checks"].values())


def test_alpha839_debits_settled_export_from_replay_soc() -> None:
    state = _state()
    result = _reconcile(state)
    agile = state["periods"]["today"]["agile_smart_export"]

    assert agile["replay_ending_soc_percent"] == 74.3
    assert agile["settled_battery_export_delta_kwh"] == 3.0
    assert agile["settled_soc_delta_percent"] == 5.597
    assert agile["ending_soc_percent"] == 68.703
    assert result["ending_soc_percent"] == 68.703
    assert state["current_routing_snapshot"]["simulated_soc_percent"] == 68.703


def test_alpha839_settlement_is_idempotent() -> None:
    state = _state()
    first = _reconcile(state)
    snapshot = json.dumps(state, sort_keys=True)
    second = _reconcile(state)

    assert first["grid_export_kwh"] == second["grid_export_kwh"] == 3.25
    assert first["ending_soc_percent"] == second["ending_soc_percent"] == 68.703
    assert json.dumps(state, sort_keys=True) == snapshot


def test_only_same_local_day_digital_twin_outcomes_are_used() -> None:
    helper = _load_helper()
    state = _state()
    result = helper.reconcile_current_day_settlements(
        state,
        _settlements()[2:],
        datetime(2026, 8, 28, 8, 50, tzinfo=LONDON),
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
    )
    assert result["applied"] is False
    assert state["periods"]["today"]["agile_smart_export"]["grid_export_kwh"] == 9.25


def test_runtime_join_runs_after_shadow_settlement_without_hardware_writes() -> None:
    runtime = (INTEGRATION / "agile_smart_export_runtime.py").read_text()
    coordinator = (INTEGRATION / "coordinator.py").read_text()
    helper_source = (INTEGRATION / "agile_current_day_settlement.py").read_text()

    assert "SettledCurrentDayAgileSmartExportManager" in runtime
    assert "reconcile_current_day_settlements" in coordinator
    assert coordinator.index(
        "await self._shadow_validation.async_update("
    ) < coordinator.index("reconcile_current_day_settlements")
    assert "self._publish(self._state)" in helper_source
    assert ".services.async_call(" not in helper_source
    assert "providers.foxess" not in helper_source
    assert '"hardware_writes": "blocked"' in helper_source


def test_alpha839_version_and_release_scope() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    bundle = json.loads((ROOT / "release/kems-bundle.template.json").read_text())

    assert manifest["version"] == "0.8.0-alpha8.39"
    assert bundle["maintenance"]["affected_components"] == [
        "kems_core",
        "dashboard",
    ]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.4"
