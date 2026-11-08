"""Completed reward-hour flow is observed energy, never the Agile replay."""

from __future__ import annotations

import importlib
import sys
import types
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "kems"
START = datetime(2026, 11, 8, 8, tzinfo=UTC)


def _load():
    custom = sys.modules.setdefault(
        "custom_components", types.ModuleType("custom_components")
    )
    custom.__path__ = [str(INTEGRATION.parent)]
    package = sys.modules.setdefault(
        "custom_components.kems", types.ModuleType("custom_components.kems")
    )
    package.__path__ = [str(INTEGRATION)]
    return importlib.import_module(
        "custom_components.kems.happy_hour_observed_flow"
    ).overlay_completed_happy_hour_flow


def _case():
    slots = [
        {
            "valid_from": (START + timedelta(minutes=30 * i)).isoformat(),
            "valid_to": (START + timedelta(minutes=30 * (i + 1))).isoformat(),
            "battery_to_home_kwh": 0.9,
            "solar_generation_kwh": 0.0,
            "flow_battery_action": "HOME",  # Stale simulation.
            "flow_grid_import_kwh": 0.0,
        }
        for i in range(2)
    ]
    readings = []
    physical = []
    for i in range(-1, 13):
        at = START + timedelta(minutes=5 * i)
        readings.append(SimpleNamespace(timestamp=at, grid_import_kw=6.0))
        physical.append(
            SimpleNamespace(
                timestamp=at,
                grid_import_kw=6.0,
                grid_export_kw=0.0,
                solar_power_kw=1.0,
                house_load_kw=1.0,
                battery_power_kw=-6.0,
            )
        )
    booking = {
        "start": START.isoformat(),
        "end": (START + timedelta(hours=1)).isoformat(),
        "event_id": "8306",
        "booking_source": "octopus_joined_events",
    }
    return {
        "state": {"today_slots": slots},
        "completed_booked_hours": [booking],
        "meter_samples": readings,
        "physical_history": physical,
        "now": START + timedelta(hours=2),
    }


def test_completed_hour_shows_physical_grid_and_charge_not_simulated_discharge():
    data = _case()
    raw = deepcopy(data["state"]["today_slots"])
    report = _load()(**data)
    assert report["status"] == "verified_completed_happy_hour_flows"
    assert report["completed_slots_with_physical_flow"] == 2
    for i, slot in enumerate(data["state"]["today_slots"]):
        assert slot["flow_grid_action"] == "IMPORT"
        assert slot["flow_battery_action"] == "CHARGE"
        assert slot["flow_grid_import_kwh"] == 3.0
        assert slot["flow_battery_charge_kwh"] == 3.0
        assert slot["flow_solar_to_home_kwh"] == 0.5
        assert slot["flow_battery_to_home_kwh"] == 0.0
        assert slot["flow_estimated_soc_percent"] is None
        assert "physical energy" in slot["flow_basis"]
        assert slot["flow_happy_hour_booking_id"] == "8306"
        assert all(slot["flow_checks"].values())
        # Actual grid/battery changes only the flow_ display contract.
        for k in ("battery_to_home_kwh", "solar_generation_kwh"):
            assert slot[k] == raw[i][k]


def test_unverified_booking_cannot_rewrite_history():
    data = _case()
    data["completed_booked_hours"][0]["booking_source"] = "manual"
    original = deepcopy(data["state"])
    report = _load()(**data)
    assert report["completed_slots_with_physical_flow"] == 0
    assert data["state"] == original


def test_no_past_half_hour_is_inferred_from_missing_meter_evidence():
    data = _case()
    data["meter_samples"] = [
        row
        for row in data["meter_samples"]
        if not START + timedelta(minutes=11)
        <= row.timestamp
        <= START + timedelta(minutes=35)
    ]
    report = _load()(**data)
    assert report["incomplete_meter_slots"] >= 1
    assert report["completed_slots_with_physical_flow"] < 2


def test_disagreeing_physical_power_balance_leaves_replay_unchanged():
    data = _case()
    for record in data["physical_history"]:
        record.battery_power_kw = 0.0
    original = deepcopy(data["state"])
    report = _load()(**data)
    assert report["energy_balance_failed_slots"] == 2
    assert data["state"] == original


def test_current_reward_half_hour_not_overwritten():
    data = _case()
    data["now"] = START + timedelta(minutes=10)
    report = _load()(**data)
    assert report["completed_slots_with_physical_flow"] == 0
    assert data["state"]["today_slots"][0]["flow_battery_action"] == "HOME"
