"""Regression tests for the Alpha9.87 mid-EV Force Charge release hazard."""

from __future__ import annotations

from kems_core.control_write_authority import should_freeze_owned_ev_hold


def _midcharge_hold(
    *,
    last_action: str = "force_charge",
    min_soc_readback: float | None = 46.0,
    last_verified: float | None = 46.0,
    connected: bool | None = True,
    cheap_confirmed: bool = True,
    authority_recovered: bool = False,
    guard_active: bool = True,
    import_exceeded: bool = False,
    eps_critical: bool = False,
    emergency: bool = False,
    island: bool = False,
    grid: bool = True,
    pending: bool = False,
) -> bool:
    return should_freeze_owned_ev_hold(
        owned_by_kems=True,
        latched_min_soc_percent=46.0,
        last_applied_action=last_action,
        observed_min_soc_on_grid_percent=min_soc_readback,
        last_verified_min_soc_on_grid_percent=last_verified,
        cheap_period_confirmed=cheap_confirmed,
        source_uncertainty_grace_active=False,
        no_paid_export_mode=True,
        ev_connected=connected,
        operating_mode="control",
        master_control_enabled=True,
        user_commissioned=True,
        emergency_stop=emergency,
        island_mode_active=island,
        grid_available=grid,
        pending_intelligent_ev_hold_active=pending,
        write_authority_recovered=authority_recovered,
        ev_hold_guard_active=guard_active,
        force_charge_hold_authorised=True,
        site_import_limit_exceeded=import_exceeded,
        eps_critical=eps_critical,
    )


def test_midcharge_loss_preserves_verified_force_charge_reserve() -> None:
    # Reproduces the 12 Oct 23:33 sequence: live EV, verified MinSOC, lost
    # control authority. No restore to 10% while the EV could drain battery.
    assert _midcharge_hold()


def test_recovered_authority_returns_to_normal_existing_control_path() -> None:
    assert not _midcharge_hold(authority_recovered=True)


def test_ev_temporarily_unknown_retains_previous_verified_floor() -> None:
    assert _midcharge_hold(connected=None)


def test_unverified_min_soc_never_claims_a_protective_hold() -> None:
    assert not _midcharge_hold(min_soc_readback=10.0)
    assert not _midcharge_hold(min_soc_readback=None, last_verified=None)
    assert not _midcharge_hold(min_soc_readback=None, last_verified=46.0, pending=True)


def test_no_ev_guard_or_confirmed_cheap_window_cannot_freeze() -> None:
    assert not _midcharge_hold(guard_active=False)
    assert not _midcharge_hold(cheap_confirmed=False)
    assert not _midcharge_hold(connected=False)


def test_site_import_and_eps_emergency_take_precedence() -> None:
    assert not _midcharge_hold(import_exceeded=True)
    assert not _midcharge_hold(eps_critical=True)
    assert not _midcharge_hold(emergency=True)
    assert not _midcharge_hold(island=True)
    assert not _midcharge_hold(grid=False)


def test_self_use_hold_and_unknown_action() -> None:
    assert _midcharge_hold(last_action="self_use")
    assert not _midcharge_hold(last_action=None)
