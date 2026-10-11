"""Regression coverage for Alpha9.85 EV hold recovery gating."""

from __future__ import annotations

from kems_core.control_write_authority import should_freeze_owned_ev_hold


def _freeze(
    *,
    write_authority_recovered: bool = False,
    ev_connected: bool | None = True,
    observed_min_soc: float | None = 52.0,
    verified_min_soc: float | None = 52.0,
    emergency_stop: bool = False,
    island_mode: bool = False,
    grid_available: bool = True,
    source_grace: bool = False,
    cheap_confirmed: bool = True,
    pending_intelligent: bool = False,
) -> bool:
    return should_freeze_owned_ev_hold(
        owned_by_kems=True,
        latched_min_soc_percent=52.0,
        last_applied_action="self_use",
        observed_min_soc_on_grid_percent=observed_min_soc,
        last_verified_min_soc_on_grid_percent=verified_min_soc,
        cheap_period_confirmed=cheap_confirmed,
        source_uncertainty_grace_active=source_grace,
        no_paid_export_mode=True,
        ev_connected=ev_connected,
        operating_mode="control",
        master_control_enabled=True,
        user_commissioned=True,
        emergency_stop=emergency_stop,
        island_mode_active=island_mode,
        grid_available=grid_available,
        pending_intelligent_ev_hold_active=pending_intelligent,
        write_authority_recovered=write_authority_recovered,
    )


def test_verified_hold_freezes_while_authority_not_recovered() -> None:
    assert _freeze()


def test_verified_hold_releases_after_explicit_authority_recovery() -> None:
    assert not _freeze(write_authority_recovered=True)


def test_unknown_ev_state_keeps_verified_hold_frozen() -> None:
    assert _freeze(ev_connected=None)


def test_uncertainty_grace_keeps_verified_hold_frozen() -> None:
    assert _freeze(source_grace=True, cheap_confirmed=False)


def test_pending_intelligent_hold_requires_live_readback() -> None:
    assert _freeze(pending_intelligent=True)
    assert not _freeze(
        pending_intelligent=True,
        observed_min_soc=None,
        verified_min_soc=52.0,
    )


def test_readback_below_floor_cannot_be_claimed_as_verified_hold() -> None:
    assert not _freeze(observed_min_soc=50.0)


def test_emergency_and_grid_failure_do_not_claim_frozen_hold() -> None:
    assert not _freeze(emergency_stop=True)
    assert not _freeze(island_mode=True)
    assert not _freeze(grid_available=False)


def test_expired_cheap_window_does_not_keep_hold_frozen() -> None:
    assert not _freeze(cheap_confirmed=False)
