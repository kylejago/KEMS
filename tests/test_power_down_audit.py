"""Regression tests for Power Down active-session safety auditing."""

from kems_core import PowerDownAuditState, finalise_power_down_audit


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


def test_session_without_active_sample_is_not_marked_successful() -> None:
    assert finalise_power_down_audit(PowerDownAuditState()) == (
        False,
        "session_activity_not_observed",
    )
