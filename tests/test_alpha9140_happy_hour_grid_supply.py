"""Alpha9.140: a full reward-hour battery must not discharge into household load.

Scope: grid-hold intent is separately booked/ledger-authorised; battery charging
remains subject to independent physical charge-headroom and FoxESS gates.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
import types

import pytest

from kems_core import ControlState, Snapshot
from kems_core.control_write_authority import (
    assess_foxess_control_write_authority,
    resolve_live_min_soc_on_grid,
)

# CI intentionally does not install Home Assistant; use the same isolated
# integration module stubs as test_alpha9_2_happy_hour.py.
INTEGRATION_DIR = Path(__file__).parents[1] / "custom_components" / "kems"


def _load_budget():
    custom_components = sys.modules.setdefault(
        "custom_components", types.ModuleType("custom_components")
    )
    custom_components.__path__ = [str(INTEGRATION_DIR.parent)]
    package = sys.modules.setdefault(
        "custom_components.kems", types.ModuleType("custom_components.kems")
    )
    package.__path__ = [str(INTEGRATION_DIR)]
    homeassistant = sys.modules.setdefault(
        "homeassistant", types.ModuleType("homeassistant")
    )
    helpers = sys.modules.setdefault(
        "homeassistant.helpers", types.ModuleType("homeassistant.helpers")
    )
    entity_registry = sys.modules.setdefault(
        "homeassistant.helpers.entity_registry",
        types.ModuleType("homeassistant.helpers.entity_registry"),
    )
    storage = sys.modules.setdefault(
        "homeassistant.helpers.storage",
        types.ModuleType("homeassistant.helpers.storage"),
    )
    storage.Store = object
    helpers.entity_registry = entity_registry
    helpers.storage = storage
    homeassistant.helpers = helpers

    name = "custom_components.kems.happy_hour_budget"
    spec = importlib.util.spec_from_file_location(
        name, INTEGRATION_DIR / "happy_hour_budget.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load isolated Happy Hour budget")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_budget = _load_budget()
apply_happy_hour_control = _budget.apply_happy_hour_control
verified_live_happy_hour_house_grid_hold = (
    _budget.verified_live_happy_hour_house_grid_hold
)

START = datetime(2026, 10, 25, 11, tzinfo=UTC)
NOW = START + timedelta(minutes=30)


def _case():
    booking = {
        "status": "booked",
        "bookings": [
            {
                "start": START.isoformat(),
                "end": (START + timedelta(hours=1)).isoformat(),
                "event_id": "7723",
                "booking_source": "octopus_joined_events",
            },
            {
                "start": (START + timedelta(hours=1)).isoformat(),
                "end": (START + timedelta(hours=2)).isoformat(),
                "event_id": "7724",
                "booking_source": "octopus_joined_events",
            },
        ],
    }
    context = {
        "start": START.isoformat(),
        "end": (START + timedelta(hours=2)).isoformat(),
        "mode": "charging",
        "happy_hour_import_authority_active": True,
        "current_reward_hour_start": START.isoformat(),
        "current_reward_hour_end": (START + timedelta(hours=1)).isoformat(),
        "current_reward_hour_ledger_complete": True,
        "current_reward_hour_cap_reached": False,
        "current_reward_hour_remaining_kwh": 15.998,
        "charge_target_kw": 0.0,
        "physical_charge_target_kw": 0.0,
        "ev_happy_hour_allowed": False,
    }
    snapshot = Snapshot(
        timestamp=NOW,
        battery_soc=100.0,
        battery_power_kw=1.376,  # physical house discharge seen in Alpha9.137
        house_load_kw=3.322,
        solar_power_kw=1.961,
        grid_import_kw=0.021,
        source_age_seconds={"house_load_kw": 10, "solar_power_kw": 10},
        ev_connected=False,
    )
    control = ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_economic_floor_hold",
        desired_work_mode="Self Use",
        desired_min_soc_percent=15.0,
        desired_battery_to_home_power_kw=1.376,
        desired_battery_export_power_kw=0.0,
        desired_total_discharge_power_kw=1.376,
        desired_grid_export_allowed=True,
        grid_available=True,
        data_fresh=True,
        plan_safe=True,
        control_enabled=True,
        commissioned=True,
        preflight_passed=27,
        preflight_total=27,
    )
    return {
        "booking": booking,
        "context": context,
        "snapshot": snapshot,
        "control": control,
        "now": NOW,
        "power_down_active": False,
    }


def _decision(control, **kw):
    return assess_foxess_control_write_authority(
        control,
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=False,
        cheap_period_confirmed=False,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
        happy_hour_house_grid_hold_authorised=kw.get("hold", False),
        happy_hour_charge_authorised=kw.get("charge", False),
    )


def test_25_oct_full_battery_still_holds_household_battery_discharge():
    args = _case()
    assert verified_live_happy_hour_house_grid_hold(**args)
    args["context"]["physical_house_grid_hold_authorised"] = True
    overlaid = apply_happy_hour_control(
        args["control"], args["snapshot"], args["context"]
    )
    assert overlaid.operating_reason == "happy_hour_reward_hour"
    assert overlaid.desired_work_mode == "Self Use"
    assert overlaid.desired_min_soc_percent == 100.0
    assert overlaid.desired_battery_to_home_power_kw == 0.0
    assert overlaid.desired_battery_export_power_kw == 0.0
    assert overlaid.desired_charge_power_kw == 0.0
    assert overlaid.desired_grid_export_allowed is False

    decision = _decision(overlaid, hold=True)
    assert decision.commands_permitted
    assert decision.action == "self_use"
    assert decision.min_soc_on_grid_percent == 100.0
    assert (
        resolve_live_min_soc_on_grid(
            decision,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=15.0,
            happy_hour_house_grid_hold_authorised=True,
        )
        == 100.0
    )


@pytest.mark.parametrize(
    "change",
    [
        {"booking": {"status": "evaluating", "bookings": []}},
        {"context": {"happy_hour_import_authority_active": False}},
        {"context": {"current_reward_hour_ledger_complete": False}},
        {"context": {"current_reward_hour_cap_reached": True}},
        {"context": {"current_reward_hour_remaining_kwh": 0.49}},
        {"context": {"mode": "complete"}},
        {"power_down_active": True},
        {"control": {"grid_available": False}},
        {"control": {"island_mode_active": True}},
        {"control": {"site_import_limit_exceeded": True}},
        {"control": {"alpha969_routing_shadow_only": True}},
        {"snapshot": {"stale_fields": ("house_load_kw",)}},
        {
            "snapshot": {
                "source_age_seconds": {"house_load_kw": 180, "solar_power_kw": 10}
            }
        },
    ],
)
def test_household_grid_hold_fails_closed_without_each_independent_proof(change):
    args = _case()
    for key, replacement in change.items():
        if key in {"snapshot", "control"}:
            args[key] = replace(args[key], **replacement)
        elif key == "context":
            args[key].update(replacement)
        else:
            args[key] = replacement
    assert not verified_live_happy_hour_house_grid_hold(**args)


def test_event_end_cannot_leave_high_min_soc_at_expensive_tariff():
    args = _case()
    assert not verified_live_happy_hour_house_grid_hold(
        **{**args, "now": START + timedelta(hours=2)}
    )
    overlaid = apply_happy_hour_control(
        args["control"],
        args["snapshot"],
        {**args["context"], "physical_house_grid_hold_authorised": True},
    )
    # A remembered high planner value is not independent event authority.
    decision = _decision(overlaid, hold=False)
    assert decision.action == "self_use"
    assert (
        resolve_live_min_soc_on_grid(
            decision,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=15.0,
            happy_hour_house_grid_hold_authorised=False,
        )
        == 15.0
    )


def test_physical_charge_remains_separately_authorised_and_not_fabricated():
    args = _case()
    context = {
        **args["context"],
        "physical_house_grid_hold_authorised": True,
        "charge_target_kw": 7.0,
        "physical_charge_target_kw": 2.5,
    }
    control = apply_happy_hour_control(args["control"], args["snapshot"], context)
    assert control.desired_work_mode == "Force Charge"
    assert control.desired_charge_power_kw == 2.5
    assert _decision(control, hold=True, charge=False).commands_permitted is False
    allowed = _decision(control, hold=True, charge=True)
    assert allowed.action == "force_charge"
    assert allowed.force_charge_power_kw == 2.5


def test_unverified_flag_cannot_escape_preflight_and_restart_safety():
    args = _case()
    context = {
        **args["context"],
        "physical_house_grid_hold_authorised": True,
    }
    control = apply_happy_hour_control(args["control"], args["snapshot"], context)
    failed = replace(control, preflight_passed=26)
    assert not _decision(failed, hold=True).commands_permitted
    assert (
        _decision(replace(control, grid_available=False), hold=True).action == "release"
    )
    assert _decision(control, hold=False).reason != (
        "Verified Happy Hour household battery discharge hold"
    )
