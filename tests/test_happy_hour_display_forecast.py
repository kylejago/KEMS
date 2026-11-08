"""Booked Happy Hour display projections must never authorise physical writes."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import ModuleType
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"
START = datetime(2026, 11, 8, 8, tzinfo=UTC)


def _forecast():
    custom = sys.modules.setdefault("custom_components", ModuleType("custom_components"))
    custom.__path__ = [str(INTEGRATION.parent)]
    package = sys.modules.setdefault(
        "custom_components.kems", ModuleType("custom_components.kems")
    )
    package.__path__ = [str(INTEGRATION)]
    name = "custom_components.kems.happy_hour_display_forecast"
    spec = importlib.util.spec_from_file_location(
        name, INTEGRATION / "happy_hour_display_forecast.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod.overlay_booked_happy_hour_flow


def _booking(start=START, event="8306"):
    return {
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
        "event_id": event,
        "booking_source": "octopus_joined_events",
    }


def _state(start=START, entry_soc=76.4):
    previous = start - timedelta(minutes=30)
    return {
        "today_slots": [],
        "tomorrow_slots": [
            {
                "valid_from": previous.isoformat(),
                "valid_to": start.isoformat(),
                "house_load_kwh": 1.0,
                "solar_generation_kwh": 0.0,
                "flow_estimated_soc_percent": entry_soc,
            },
            *[
                {
                    "valid_from": (start + timedelta(minutes=30 * i)).isoformat(),
                    "valid_to": (start + timedelta(minutes=30 * (i + 1))).isoformat(),
                    "house_load_kwh": 0.75,
                    "solar_generation_kwh": 0.5,
                    "flow_estimated_soc_percent": entry_soc,
                    # Deliberately contradictory raw replay remains unchanged.
                    "battery_to_home_kwh": 0.25,
                    "grid_import_kwh": 0.0,
                }
                for i in range(4)
            ],
        ],
    }


def _run(state, *, bookings=None, now=None, site_limit=14.5):
    return _forecast()(
        state,
        confirmed_bookings=bookings if bookings is not None else [
            _booking(), _booking(START + timedelta(hours=1), "8307")
        ],
        now=now or START - timedelta(hours=9),
        capacity_kwh=56.42,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        site_import_limit_kw=site_limit,
    )


def test_two_confirmed_hours_show_charge_and_grid_import_without_forcing_solar_grid():
    state = _state()
    original = deepcopy(state["tomorrow_slots"])
    report = _run(state)
    assert report["status"] == "booked_happy_hour_flow_projected"
    assert report["slots_overlaid"] == 4
    assert report["hardware_writes"] == "none"
    assert report["physical_entry_soc_proven"] is False
    for i, slot in enumerate(state["tomorrow_slots"][1:], start=1):
        assert slot["flow_grid_action"] == "IMPORT"
        assert slot["flow_battery_action"] == "CHARGE"
        assert slot["flow_battery_to_home_kwh"] == 0
        assert slot["flow_battery_export_kwh"] == 0
        assert slot["flow_solar_to_home_kwh"] == 0.5
        assert slot["flow_grid_to_battery_kwh"] > 0
        assert all(slot["flow_checks"].values())
        for raw in ("battery_to_home_kwh", "grid_import_kwh"):
            assert slot[raw] == original[i][raw]
    assert report["modelled_stored_charge_kwh"] > 12
    assert sum(s["flow_grid_import_kwh"] for s in state["tomorrow_slots"][1:3]) < 16.0
    assert sum(s["flow_grid_import_kwh"] for s in state["tomorrow_slots"][3:5]) < 16.0


def test_solar_surplus_is_allowed_to_charge_the_battery_not_exported_mandatorily():
    state = _state()
    state["tomorrow_slots"][1]["solar_generation_kwh"] = 2.0
    _run(state)
    slot = state["tomorrow_slots"][1]
    assert slot["flow_solar_to_home_kwh"] == 0.75
    assert slot["flow_solar_to_battery_kwh"] == 1.25
    assert slot["flow_grid_to_battery_kwh"] > 0
    assert slot["flow_grid_import_kwh"] > 0


def test_active_or_completed_slots_are_never_rewritten():
    state = _state()
    original = deepcopy(state["tomorrow_slots"])
    report = _run(state, now=START + timedelta(minutes=46))
    assert report["slots_overlaid"] == 2
    for idx in (0, 1, 2):
        assert state["tomorrow_slots"][idx] == original[idx]
    assert state["tomorrow_slots"][3]["flow_battery_action"] == "CHARGE"


def test_no_unverified_booking_can_change_any_slot():
    state = _state()
    original = deepcopy(state)
    booking = _booking()
    booking["booking_source"] = "manual"
    report = _run(state, bookings=[booking])
    assert report["status"] == "no_confirmed_future_slots"
    assert state == original


def test_full_forecast_battery_limits_charging_without_inventing_extra_space():
    state = _state(entry_soc=99.5)
    report = _run(state)
    assert report["modelled_stored_charge_kwh"] <= 0.29
    assert state["tomorrow_slots"][1]["flow_estimated_soc_percent"] <= 100.0
    assert state["tomorrow_slots"][4]["flow_estimated_soc_percent"] <= 100.0


def test_incomplete_house_forecast_fails_closed_for_that_slot():
    state = _state()
    state["tomorrow_slots"][1]["house_load_kwh"] = None
    report = _run(state)
    assert report["status"] == "booked_happy_hour_flow_projected"
    assert report["slots_overlaid"] == 3
    assert "flow_happy_hour_booking_id" not in state["tomorrow_slots"][1]


def test_import_site_limit_is_not_exceeded_by_modelled_battery_grid_charge():
    state = _state()
    _run(state, site_limit=2.0)
    for slot in state["tomorrow_slots"][1:]:
        assert slot["flow_grid_import_kwh"] <= 1.001
