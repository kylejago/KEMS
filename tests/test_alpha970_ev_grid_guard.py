"""Physical EV protection stays within reviewed Self Use/MinSOC/cheap charge."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from kems_core import ControlConfig, ControlState, Snapshot
from kems_core.control_write_authority import assess_foxess_control_write_authority
from kems_core.ev_grid_guard import (
    protect_fixed_overnight_grid_supply,
    protect_live_cheap_ev,
    regular_overnight_grid_supply,
)

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


def _guard(
    snapshot=None,
    plan=None,
    config=None,
    *,
    no_paid_export_mode=True,
    verified_overnight_hold=False,
):
    return protect_live_cheap_ev(
        snapshot or _snap(),
        plan or _plan(),
        config or _config(),
        no_paid_export_mode=no_paid_export_mode,
        verified_overnight_hold=verified_overnight_hold,
    )


def test_verified_ev_inside_site_load_preserves_one_count_and_charge_headroom():
    state = _guard()
    assert state.ev_grid_guard_status == "ev_battery_hold_with_cheap_charge"
    assert state.desired_min_soc_percent == 61.0
    assert state.desired_work_mode == "Force Charge"
    assert state.desired_charge_power_kw == 5.0
    assert state.grid_bypass_power_kw == 8.0
    assert state.total_site_import_kw == 13.0
    assert state.site_import_headroom_kw == 1.5
    assert state.plan_safe
    assert state.desired_battery_to_home_power_kw == 0.0


@pytest.mark.parametrize("scope", [False, None])
def test_outside_or_unknown_ev_membership_is_counted_conservatively(scope):
    state = _guard(
        _snap(ev_load_in_house_load=scope, house_load_kw=2.0),
        _plan(grid_bypass_power_kw=2.0),
    )
    assert state.grid_bypass_power_kw == 8.5
    assert state.desired_charge_power_kw == 5.0
    assert state.total_site_import_kw == 13.5
    assert state.ev_grid_guard_status.endswith("_conservative_scope")
    assert not state.desired_grid_export_allowed


def test_real_7_56_kw_ev_and_normal_home_load_leave_measured_import_reserve():
    state = _guard(
        _snap(ev_power_kw=7.558, ev_load_in_house_load=None, house_load_kw=1.4),
        _plan(grid_bypass_power_kw=1.4),
    )
    assert state.desired_work_mode == "Force Charge"
    assert state.desired_charge_power_kw == 4.792
    assert state.total_site_import_kw == 13.75
    assert state.site_import_headroom_kw == 0.75
    assert state.plan_safe


def test_high_household_load_reduces_charge_below_five_without_ev_discharge():
    state = _guard(
        _snap(ev_power_kw=7.558, ev_load_in_house_load=None, house_load_kw=5.069),
        _plan(grid_bypass_power_kw=5.069),
    )
    assert state.desired_charge_power_kw == 1.123
    assert state.total_site_import_kw == 13.75
    assert state.site_import_headroom_kw == 0.75
    assert state.desired_battery_to_home_power_kw == 0.0
    assert state.desired_total_discharge_power_kw == 0.0
    assert state.desired_min_soc_percent == 61.0


def test_no_charge_headroom_preserves_existing_physical_ev_hold():
    state = _guard(
        _snap(ev_power_kw=7.558, ev_load_in_house_load=None, house_load_kw=6.4),
        _plan(grid_bypass_power_kw=6.4),
    )
    assert state.desired_charge_power_kw == 0.0
    assert state.desired_work_mode == "Self Use"
    assert state.desired_min_soc_percent == 61.0
    assert state.desired_total_discharge_power_kw == 0.0
    assert state.plan_safe


def test_existing_lower_charge_limit_and_inactive_ev_remain_unchanged():
    active = _guard(
        _snap(ev_load_in_house_load=None, house_load_kw=1.0),
        _plan(grid_bypass_power_kw=1.0, desired_charge_power_kw=2.0),
    )
    assert active.desired_charge_power_kw == 2.0
    assert active.desired_work_mode == "Force Charge"
    assert (
        _guard(
            _snap(ev_charging=False, ev_power_kw=0.0),
            _plan(desired_charge_power_kw=7.0),
        ).desired_charge_power_kw
        == 7.0
    )


def test_original_uncapped_cheap_charge_site_failure_is_rebudgeted_safely():
    original = _plan(
        plan_safe=False,
        site_import_limit_exceeded=True,
        blocked_reason="Configured site-import limit leaves no safe charging headroom",
    )
    corrected = _guard(plan=original)
    assert corrected.plan_safe
    assert corrected.site_import_limit_exceeded is False
    assert corrected.desired_charge_power_kw == 5.0
    assert corrected.total_site_import_kw == 13.0
    assert corrected.blocked_reason == ""


def test_non_site_safety_failure_is_not_waived_by_headroom_rebudget():
    original = _plan(plan_safe=False, blocked_reason="Other safety gate failed")
    corrected = _guard(plan=original)
    assert corrected.plan_safe is False
    assert corrected.blocked_reason == "Other safety gate failed"


def test_grid_ct_containing_existing_charge_is_not_added_again():
    state = _guard(_snap(grid_import_kw=14.25), _plan())
    assert state.desired_charge_power_kw == 5.0
    assert state.total_site_import_kw == 13.0
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


def test_connected_idle_ev_prearms_floor_without_cancelling_safe_charge():
    state = _guard(
        _snap(ev_charging=False, ev_power_kw=0.0, battery_soc=60.0),
        _plan(
            desired_work_mode="Force Charge",
            desired_charge_power_kw=6.0,
            desired_min_soc_percent=54.0,
            grid_bypass_power_kw=1.0,
            total_site_import_kw=7.0,
        ),
    )
    assert state.ev_grid_guard_status == "ev_battery_hold_prearmed"
    assert state.desired_min_soc_percent == 61.0
    assert state.desired_work_mode == "Force Charge"
    assert state.desired_charge_power_kw == 6.0
    assert state.desired_battery_to_home_power_kw == 0.0


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
    assert decision(charge).force_charge_power_kw == 5.0
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
    live_backend_call = (
        "control=control,\n"
        "                snapshot=snapshot,\n"
        "                technical_ready="
    )
    shadow_backend_call = (
        "control=proposal,\n"
        "                snapshot=snapshot,\n"
        "                technical_ready="
    )
    assert live_backend_call in coordinator
    assert shadow_backend_call not in coordinator
    backend = (root / "foxess_control_backend.py").read_text(encoding="utf-8")
    live = backend.split("async def async_update(", 1)[1].split("payload =", 1)[0]
    assert 'decision.action == "force_discharge"' in live
    assert "not no_paid_export_mode" in live
    assert '"import_power_limit"' not in live
    assert "export_power_limit_write" in backend
    assert 'key="ev_grid_guard"' in (root / "sensor.py").read_text(encoding="utf-8")


def test_november_26_false_double_count_suspends_charge_without_release():
    snapshot = _snap(
        ev_power_kw=7.459,
        ev_load_in_house_load=None,
        house_load_kw=8.689,
        grid_import_kw=1.456,
        battery_power_kw=7.622,
        grid_export_kw=0.0,
        battery_soc=59.0,
        source_age_seconds={
            "house_load_kw": 4.9,
            "battery_power_kw": 4.9,
            "grid_import_kw": 4.9,
        },
    )
    plan = _plan(grid_bypass_power_kw=8.689)
    guarded = _guard(snapshot, plan)
    state = protect_fixed_overnight_grid_supply(snapshot, guarded, _config())
    assert state.plan_safe
    assert not state.site_import_limit_exceeded
    assert state.desired_work_mode == "Self Use"
    assert state.desired_charge_power_kw == 0.0
    assert state.desired_min_soc_percent == 100.0
    assert state.total_site_import_kw == 9.078
    assert state.desired_total_discharge_power_kw == 0.0
    decision = assess_foxess_control_write_authority(
        state,
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=False,
        cheap_period_confirmed=True,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
    )
    assert decision.commands_permitted
    assert decision.action == "self_use"
    assert decision.min_soc_on_grid_percent == 100.0


@pytest.mark.parametrize("battery_power", [1.0, 13.5])
def test_unbalanced_or_genuinely_over_limit_load_is_not_waived(battery_power):
    snapshot = _snap(
        ev_power_kw=7.459,
        ev_load_in_house_load=None,
        house_load_kw=8.689,
        grid_import_kw=1.456,
        battery_power_kw=battery_power,
        grid_export_kw=0.0,
        source_age_seconds={
            "house_load_kw": 4.9,
            "battery_power_kw": 4.9,
            "grid_import_kw": 4.9,
        },
    )
    assert not _guard(snapshot, _plan(grid_bypass_power_kw=8.689)).plan_safe


@pytest.mark.parametrize("charge", [0.0, 5.0])
def test_fixed_overnight_hold_independent_of_ev_presence(charge):
    snapshot = _snap(ev_connected=False, ev_charging=False, ev_power_kw=0.0)
    plan = _plan(desired_charge_power_kw=charge)
    state = protect_fixed_overnight_grid_supply(snapshot, plan, _config())
    assert state.desired_min_soc_percent == 100.0
    assert state.desired_charge_power_kw == charge
    assert state.desired_work_mode == ("Force Charge" if charge else "Self Use")
    assert state.desired_total_discharge_power_kw == 0.0


@pytest.mark.parametrize(
    ("snap_updates", "plan_updates", "config_updates"),
    [
        ({"off_peak": False}, {}, {}),
        ({"saving_session_active": True}, {}, {}),
        ({}, {"operating_reason": "happy_hour_reward_hour"}, {}),
        ({}, {"site_import_limit_exceeded": True, "plan_safe": False}, {}),
        ({}, {"grid_available": False}, {}),
        ({}, {}, {"emergency_stop": True}),
        ({}, {"data_fresh": False}, {}),
    ],
)
def test_regular_hold_does_not_override_other_safety_or_tariff_paths(
    snap_updates, plan_updates, config_updates
):
    plan = _plan(**plan_updates)
    assert (
        protect_fixed_overnight_grid_supply(
            _snap(**snap_updates), plan, _config(**config_updates)
        )
        is plan
    )


def test_regular_hold_keeps_measured_overload_veto():
    state = protect_fixed_overnight_grid_supply(
        _snap(grid_import_kw=14.8), _plan(), _config()
    )
    assert not state.plan_safe
    assert state.site_import_limit_exceeded
    assert state.desired_charge_power_kw == 0.0


def test_unknown_scope_can_suspend_an_existing_charge_without_releasing():
    snapshot = _snap(
        ev_power_kw=7.459,
        ev_load_in_house_load=None,
        house_load_kw=8.689,
        grid_import_kw=13.689,
        battery_power_kw=-5.0,
        grid_export_kw=0.0,
        source_age_seconds={
            "house_load_kw": 4.9,
            "battery_power_kw": 4.9,
            "grid_import_kw": 4.9,
        },
    )
    guarded = _guard(snapshot, _plan(grid_bypass_power_kw=8.689))
    state = protect_fixed_overnight_grid_supply(snapshot, guarded, _config())
    assert state.plan_safe
    assert state.desired_work_mode == "Self Use"
    assert state.desired_charge_power_kw == 0.0
    assert state.desired_min_soc_percent == 100.0
    assert state.total_site_import_kw == 8.689


def _november_28_snapshot(**updates):
    data = dict(
        ev_power_kw=7.224,
        ev_load_in_house_load=None,
        house_load_kw=10.732,
        grid_import_kw=12.719,
        battery_power_kw=-2.093,
        grid_export_kw=0.0,
        battery_soc=17.0,
        source_data_age_seconds=54.6,
        source_age_seconds={
            "house_load_kw": 4.6,
            "battery_power_kw": 54.6,
            "grid_import_kw": 4.6,
        },
    )
    data.update(updates)
    return _snap(**data)


def test_november_28_delayed_charging_report_does_not_release_overnight_hold():
    snapshot = _november_28_snapshot()
    plan = _plan(grid_bypass_power_kw=10.732)
    state = protect_fixed_overnight_grid_supply(
        snapshot, _guard(snapshot, plan, verified_overnight_hold=True), _config()
    )
    assert state.plan_safe
    assert not state.site_import_limit_exceeded
    assert state.desired_work_mode == "Self Use"
    assert state.desired_charge_power_kw == 0.0
    assert state.desired_min_soc_percent == 100.0
    assert state.total_site_import_kw == 12.719
    assert state.desired_total_discharge_power_kw == 0.0
    assert "CT-only no-charge hold" in state.next_action
    decision = assess_foxess_control_write_authority(
        state,
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=False,
        cheap_period_confirmed=True,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
    )
    assert decision.commands_permitted
    assert decision.action == "self_use"
    assert decision.min_soc_on_grid_percent == 100.0


@pytest.mark.parametrize(
    "updates",
    [
        {"grid_import_kw": 14.8},
        {"battery_power_kw": 2.093},
        {"battery_power_kw": -0.1},
        {"ev_load_in_house_load": False},
        {
            "source_age_seconds": {
                "house_load_kw": 4.6,
                "battery_power_kw": 91.0,
                "grid_import_kw": 4.6,
            }
        },
        {
            "source_age_seconds": {
                "house_load_kw": 15.0,
                "battery_power_kw": 54.6,
                "grid_import_kw": 4.6,
            }
        },
        {"tariff_stale_fields": ("off_peak",)},
    ],
)
def test_delayed_charge_hold_does_not_waive_real_or_unverified_overload(updates):
    state = _guard(
        _november_28_snapshot(**updates),
        _plan(grid_bypass_power_kw=10.732),
        verified_overnight_hold=True,
    )
    assert not state.plan_safe
    assert state.desired_charge_power_kw == 0.0


def test_delayed_charge_hold_does_not_waive_unrelated_failure():
    state = _guard(
        _november_28_snapshot(),
        _plan(
            grid_bypass_power_kw=10.732,
            plan_safe=False,
            blocked_reason="Other safety gate failed",
        ),
        verified_overnight_hold=True,
    )
    assert not state.plan_safe


def test_confirmed_scope_resumes_capped_charge_after_delayed_report():
    snapshot = _november_28_snapshot(ev_load_in_house_load=True)
    state = protect_fixed_overnight_grid_supply(
        snapshot, _guard(snapshot, _plan(grid_bypass_power_kw=10.732)), _config()
    )
    assert state.plan_safe
    assert state.desired_work_mode == "Force Charge"
    assert state.desired_charge_power_kw == 3.018
    assert state.desired_min_soc_percent == 100.0


def test_delayed_charge_report_cannot_establish_new_unverified_hold():
    state = _guard(
        _november_28_snapshot(),
        _plan(grid_bypass_power_kw=10.732),
    )
    assert not state.plan_safe
    assert state.desired_charge_power_kw == 0.0


@pytest.mark.parametrize(
    "changes, expected_charge",
    [
        ({}, 5.0),
        (
            {"ev_charging": False, "ev_power_kw": 0.0, "house_load_kw": 1.0},
            5.75,
        ),
        (
            {"ev_connected": False, "ev_charging": False, "ev_power_kw": 0.0},
            5.75,
        ),
        (
            {
                "ev_load_in_house_load": None,
                "battery_power_kw": 1.0,
                "source_age_seconds": {"grid_import_kw": 2.0, "battery_power_kw": 2.0},
            },
            0.0,
        ),
    ],
)
def test_regular_overnight_floor_is_independent_of_ev(changes, expected_charge):
    state = regular_overnight_grid_supply(_snap(**changes), _plan(), _config())
    assert state.plan_safe
    assert state.desired_min_soc_percent == 100.0
    assert state.desired_total_discharge_power_kw == 0.0
    assert state.desired_charge_power_kw == expected_charge


def test_regular_overnight_replacement_import_veto():
    state = regular_overnight_grid_supply(
        _snap(
            grid_import_kw=12.0,
            battery_power_kw=4.0,
            source_age_seconds={"grid_import_kw": 2.0, "battery_power_kw": 2.0},
        ),
        _plan(),
        _config(),
    )
    assert not state.plan_safe
    assert state.site_import_limit_exceeded
    assert state.desired_charge_power_kw == 0.0


def test_regular_overnight_incident_delayed_battery_report():
    state = regular_overnight_grid_supply(
        _november_28_snapshot(),
        _plan(grid_bypass_power_kw=10.732),
        _config(),
        verified_overnight_hold=True,
    )
    assert state.plan_safe
    assert state.desired_work_mode == "Self Use"
    assert state.desired_min_soc_percent == 100.0
    assert state.desired_charge_power_kw == 0.0


def test_regular_overnight_does_not_override_island_or_emergency():
    for control, config in (
        (_plan(grid_available=False, island_mode_active=True), _config()),
        (_plan(), _config(emergency_stop=True)),
    ):
        assert regular_overnight_grid_supply(_snap(), control, config) == control
