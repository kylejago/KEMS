"""Physical EV protection stays within reviewed Self Use/MinSOC/cheap charge."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from kems_core import ControlConfig, ControlState, Snapshot
from kems_core.control_write_authority import assess_foxess_control_write_authority
from kems_core.ev_grid_guard import protect_live_cheap_ev

WHEN = datetime(2026, 9, 27, 23, 30, tzinfo=ZoneInfo("Europe/London"))


def _snap(**updates) -> Snapshot:
    data = dict(
        timestamp=WHEN,
        off_peak=True,
        ev_connected=True,
        ev_charging=True,
        ev_power_kw=6.5,
        ev_power_age_seconds=5.0,
        ev_load_in_house_load=True,
        battery_soc=60.0,
        house_load_kw=8.0,
        solar_power_kw=0.0,
        grid_import_kw=7.0,
        source_data_age_seconds=5.0,
        stale_fields=(),
    )
    data.update(updates)
    return Snapshot(**data)


def _plan(**updates) -> ControlState:
    data = dict(
        operating_mode="control",
        operating_reason="awaiting_export_tariff_charge",
        desired_work_mode="Force Charge",
        desired_charge_power_kw=7.0,
        desired_min_soc_percent=60.0,
        grid_bypass_power_kw=8.0,
        total_site_import_kw=15.0,
        site_import_limit_kw=14.5,
        desired_grid_export_allowed=False,
        data_fresh=True,
        plan_safe=True,
        preflight_total=15,
        preflight_passed=15,
    )
    data.update(updates)
    return ControlState(**data)


def _config(**updates) -> ControlConfig:
    data = dict(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        max_charge_kw=7.0,
        site_import_limit_kw=14.5,
        normal_reserve_percent=15.0,
    )
    data.update(updates)
    return ControlConfig(**data)


def _guard(snapshot=None, plan=None, config=None, *, no_paid_export_mode=True):
    return protect_live_cheap_ev(
        snapshot or _snap(),
        plan or _plan(),
        config or _config(),
        no_paid_export_mode=no_paid_export_mode,
    )


def test_verified_ev_inside_site_load_preserves_one_count_and_charge_headroom():
    state = _guard()
    assert state.ev_grid_guard_status == "ev_battery_hold_with_cheap_charge"
    assert state.desired_min_soc_percent == 61.0
    assert state.desired_work_mode == "Force Charge"
    assert state.desired_charge_power_kw == 6.5
    assert state.grid_bypass_power_kw == 8.0
    assert state.total_site_import_kw == 14.5
    assert state.site_import_headroom_kw == 0
    assert state.plan_safe
    assert state.desired_battery_to_home_power_kw == 0.0


@pytest.mark.parametrize("scope", [False, None])
def test_outside_or_unknown_ev_membership_is_counted_conservatively(scope):
    state = _guard(
        _snap(ev_load_in_house_load=scope, house_load_kw=2.0),
        _plan(grid_bypass_power_kw=2.0),
    )
    assert state.grid_bypass_power_kw == 8.5
    assert state.desired_charge_power_kw == 6.0
    assert state.total_site_import_kw == 14.5
    assert state.ev_grid_guard_status.endswith("_conservative_scope")
    assert not state.desired_grid_export_allowed


def test_original_uncapped_cheap_charge_site_failure_is_rebudgeted_safely():
    original = _plan(
        plan_safe=False,
        site_import_limit_exceeded=True,
        blocked_reason="Configured site-import limit leaves no safe charging headroom",
    )
    corrected = _guard(plan=original)
    assert corrected.plan_safe
    assert corrected.site_import_limit_exceeded is False
    assert corrected.desired_charge_power_kw == 6.5
    assert corrected.total_site_import_kw == 14.5
    assert corrected.blocked_reason == ""


def test_non_site_safety_failure_is_not_waived_by_headroom_rebudget():
    original = _plan(plan_safe=False, blocked_reason="Other safety gate failed")
    corrected = _guard(plan=original)
    assert corrected.plan_safe is False
    assert corrected.blocked_reason == "Other safety gate failed"


def test_grid_ct_containing_existing_charge_is_not_added_again():
    state = _guard(_snap(grid_import_kw=14.25), _plan())
    assert state.desired_charge_power_kw == 6.5
    assert state.total_site_import_kw == 14.5
    assert state.plan_safe


def test_actual_grid_import_over_limit_inhibits_additional_charge():
    state = _guard(_snap(grid_import_kw=14.8), _plan())
    assert state.desired_charge_power_kw == 0.0
    assert not state.plan_safe
    assert state.ev_grid_guard_status == "observed_site_import_limit_exceeded"
    assert "Observed grid import exceeds" in state.blocked_reason


@pytest.mark.parametrize(
    "snap_updates",
    [
        {"ev_power_age_seconds": 150.0},
        {"ev_power_kw": None},
        {"house_load_kw": None},
        {"grid_import_kw": None},
    ],
)
def test_missing_ev_or_site_evidence_only_holds_battery(snap_updates):
    state = _guard(_snap(**snap_updates))
    assert state.ev_grid_guard_status == "battery_hold_ev_or_site_unverified"
    assert state.desired_work_mode == "Self Use"
    assert state.desired_charge_power_kw == 0.0
    assert state.desired_min_soc_percent == 61.0
    assert "No new Force Charge" in state.next_action


def test_missing_physical_soc_cannot_authorise_guard_writes():
    state = _guard(_snap(battery_soc=None))
    assert state.ev_grid_guard_status == "blocked_no_fresh_physical_soc"
    assert not state.plan_safe
    assert state.desired_work_mode == "No change"
    assert state.desired_charge_power_kw == 0


@pytest.mark.parametrize(
    ("snap_updates", "plan_updates", "config_updates", "mode"),
    [
        ({"off_peak": False}, {}, {}, True),
        ({"ev_charging": False, "ev_power_kw": 0.0}, {}, {}, True),
        ({"saving_session_active": True}, {}, {}, True),
        ({}, {"operating_reason": "happy_hour_reward_hour"}, {}, True),
        ({}, {"operating_reason": "stale_data_failsafe"}, {}, True),
        ({}, {"island_mode_active": True}, {}, True),
        ({}, {}, {"emergency_stop": True}, True),
        ({}, {"alpha969_routing_shadow_only": True}, {}, True),
        ({}, {"operating_mode": "shadow"}, {}, True),
        ({}, {}, {}, False),
    ],
)
def test_no_override_of_outside_cheap_priority_or_shadow_paths(
    snap_updates, plan_updates, config_updates, mode
):
    snap = _snap(**snap_updates)
    plan = _plan(**plan_updates)
    assert (
        _guard(snap, plan, _config(**config_updates), no_paid_export_mode=mode) is plan
    )


def test_prior_session_floor_never_chases_falling_soc_down():
    previous = 68.0
    state = protect_live_cheap_ev(
        _snap(battery_soc=62.0),
        _plan(desired_min_soc_percent=60.0),
        _config(),
        no_paid_export_mode=True,
        held_floor_percent=previous,
    )
    assert state.desired_min_soc_percent == 68.0
    assert state.ev_grid_guard_status.startswith("ev_battery_hold")


def test_unknown_ohme_after_active_scan_retains_existing_floor():
    state = protect_live_cheap_ev(
        _snap(ev_connected=None, ev_charging=None, ev_power_kw=None),
        _plan(),
        _config(),
        no_paid_export_mode=True,
        held_floor_percent=70.0,
    )
    assert state.ev_grid_guard_status == "battery_hold_ev_or_site_unverified"
    assert state.desired_min_soc_percent == 70.0
    assert state.desired_charge_power_kw == 0.0


def test_charge_and_hold_use_only_old_reviewed_backend_authority():
    charge = _guard()
    hold = _guard(_snap(ev_power_age_seconds=150.0))

    def decision(control):
        return assess_foxess_control_write_authority(
            control,
            technical_ready=True,
            binding_ready=True,
            reviewed_version_matches=True,
            no_paid_export_mode=True,
            cheap_period_confirmed=True,
            user_commissioned=True,
            master_control_enabled=True,
            emergency_stop=False,
        )

    assert decision(charge).action == "force_charge"
    assert decision(charge).force_charge_power_kw == 6.5
    assert decision(hold).action == "self_use"
    assert decision(hold).min_soc_on_grid_percent == 61.0
    assert not decision(
        replace(charge, alpha969_routing_shadow_only=True)
    ).commands_permitted
    assert not decision(replace(charge, plan_safe=False)).commands_permitted


def test_coordinator_routes_guard_only_into_reviewed_existing_backend():
    root = Path(__file__).parents[1] / "custom_components" / "kems"
    coordinator = (root / "coordinator.py").read_text(encoding="utf-8")
    assert (
        "control = apply_happy_hour_control(control, snapshot, happy_hour_plan)"
        in coordinator
    )
    assert "control = await self._ev_grid_hold.async_apply(" in coordinator
    assert "control=control,\n                technical_ready=" in coordinator
    assert "control=proposal,\n                technical_ready=" not in coordinator
    backend = (root / "foxess_control_backend.py").read_text(encoding="utf-8")
    assert (
        '"Force Discharge"'
        not in backend.split("async def async_update(", 1)[1].split("payload =", 1)[0]
    )
    assert "export_power_limit_write" in backend
    assert 'key="ev_grid_guard"' in (root / "sensor.py").read_text(encoding="utf-8")
