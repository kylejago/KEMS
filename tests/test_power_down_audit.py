"""Regression tests for Power Down active-session safety and accounting."""

import pytest
from kems_core import (
    PowerDownAccountingState,
    PowerDownAuditState,
    finalise_power_down_audit,
)


def test_joined_pre_session_sample_does_not_poison_ev_block_result() -> None:
    """EV is only required to be blocked while the Power Down is actually active."""
    audit = PowerDownAuditState().observe(
        session_active=False,
        desired_ev_charging_allowed=True,
        plan_safe=True,
        island_mode_active=False,
    )
    audit = audit.observe(
        session_active=True,
        desired_ev_charging_allowed=False,
        plan_safe=True,
        island_mode_active=False,
    )

    assert audit.active_samples_observed == 1
    assert audit.ev_successfully_blocked is True
    assert finalise_power_down_audit(audit) == (True, "completed")


def test_active_ev_allowance_fails_with_specific_reason() -> None:
    audit = PowerDownAuditState().observe(
        session_active=True,
        desired_ev_charging_allowed=True,
        plan_safe=True,
        island_mode_active=False,
    )

    assert finalise_power_down_audit(audit) == (False, "ev_block_check_failed")


def test_active_plan_failure_and_island_override_are_explicit() -> None:
    unsafe = PowerDownAuditState().observe(
        session_active=True,
        desired_ev_charging_allowed=False,
        plan_safe=False,
        island_mode_active=False,
    )
    island = PowerDownAuditState().observe(
        session_active=True,
        desired_ev_charging_allowed=False,
        plan_safe=True,
        island_mode_active=True,
    )

    assert finalise_power_down_audit(unsafe) == (False, "plan_safety_check_failed")
    assert finalise_power_down_audit(island) == (False, "island_safety_override")


def test_session_without_active_sample_is_inconclusive() -> None:
    """Missing evidence must never be presented to the user as a failed event."""
    assert finalise_power_down_audit(PowerDownAuditState()) == (
        None,
        "insufficient_active_samples",
    )


def test_power_down_accounting_integrates_final_net_site_route() -> None:
    """The 24 Aug route must retain export rather than the no-export base replay."""
    accounting = PowerDownAccountingState().observe(
        hours=1.0,
        battery_to_home_kw=4.570,
        grid_import_kw=0.0,
        grid_export_kw=1.387,
        inverter_output_kw=7.0,
        baseline_net_kw=0.979111111111112,
        bonus_rate_pence=8.5,
        export_rate_pence=0.0,
    )

    assert accounting.planned_battery_to_home_kwh == pytest.approx(4.570)
    assert accounting.planned_export_kwh == pytest.approx(1.387)
    assert accounting.maximum_inverter_output_kw == pytest.approx(7.0)
    assert accounting.rewardable_reduction_kwh == pytest.approx(2.366111111111112)
    assert accounting.bonus_pence == pytest.approx(20.111944444444452)
    assert accounting.fixed_export_income_pence == 0.0
    assert accounting.route_samples_observed == 1
    assert accounting.reward_samples_observed == 1


def test_power_down_accounting_keeps_one_direction_site_settlement() -> None:
    accounting = PowerDownAccountingState().observe(
        hours=0.5,
        battery_to_home_kw=1.2,
        grid_import_kw=0.0,
        grid_export_kw=5.0,
        inverter_output_kw=7.0,
        baseline_net_kw=None,
        bonus_rate_pence=None,
        export_rate_pence=12.0,
    )

    assert accounting.planned_export_kwh == pytest.approx(2.5)
    assert accounting.fixed_export_income_pence == pytest.approx(30.0)
    assert accounting.reward_samples_observed == 0
