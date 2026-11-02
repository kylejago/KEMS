"""Alpha9.163 household-only FoxESS MinSOC regression tests."""

from kems_core.control_write_authority import (
    FoxESSControlDecision,
    resolve_live_min_soc_on_grid,
)


def _decision(action="self_use", requested=10.0):
    return FoxESSControlDecision(
        backend_available=True,
        commands_permitted=True,
        action=action,
        reason="bounded live command",
        min_soc_on_grid_percent=requested,
    )


def test_household_only_bridge_sets_10_percent_below_baseline():
    assert (
        resolve_live_min_soc_on_grid(
            _decision(),
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=15.0,
        )
        == 10.0
    )


def test_other_noncheap_floor_preserves_original_baseline():
    assert (
        resolve_live_min_soc_on_grid(
            _decision(requested=15.0),
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=15.0,
        )
        == 15.0
    )


def test_ev_hold_does_not_drop_to_10_percent():
    assert (
        resolve_live_min_soc_on_grid(
            _decision(requested=100.0),
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=15.0,
            pending_intelligent_ev_hold_active=True,
        )
        == 100.0
    )


def test_cheap_period_keeps_force_charge_min_soc():
    assert (
        resolve_live_min_soc_on_grid(
            _decision(action="force_charge", requested=15.0),
            cheap_period_confirmed=True,
            previous_min_soc_on_grid=15.0,
        )
        == 15.0
    )



def test_alpha9171_paid_idle_household_10_percent_requires_explicit_proof():
    idle = FoxESSControlDecision(
        backend_available=True,
        commands_permitted=True,
        action="self_use",
        reason="Paid-export idle Self Use is inside the bounded live scope",
        min_soc_on_grid_percent=15.0,
    )
    kwargs = dict(
        cheap_period_confirmed=False,
        previous_min_soc_on_grid=15.0,
    )
    assert resolve_live_min_soc_on_grid(idle, **kwargs) == 15.0
    assert (
        resolve_live_min_soc_on_grid(
            idle,
            **kwargs,
            paid_idle_household_10_percent_authorised=True,
        )
        == 10.0
    )
    assert (
        resolve_live_min_soc_on_grid(
            idle,
            cheap_period_confirmed=True,
            previous_min_soc_on_grid=15.0,
            paid_idle_household_10_percent_authorised=True,
        )
        == 15.0
    )


def test_alpha9171_paid_export_and_ev_hold_never_lower_hardware_floor():
    for action, reason, soc in (
        ("force_discharge", "Paid export Force Discharge", 15.0),
        ("self_use", "Verified Happy Hour household battery discharge hold", 100.0),
        ("self_use", "No-paid-export Self Use is inside the bounded live scope", 15.0),
    ):
        decision = FoxESSControlDecision(
            backend_available=True,
            commands_permitted=True,
            action=action,
            reason=reason,
            min_soc_on_grid_percent=soc,
        )
        assert resolve_live_min_soc_on_grid(
            decision,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=15.0,
            paid_idle_household_10_percent_authorised=True,
        ) == soc


def test_alpha9171_hardware_guard_restricts_to_explicit_unplugged_sensor():
    from pathlib import Path

    source = (
        Path(__file__).parents[1]
        / "custom_components/kems/foxess_control_backend.py"
    ).read_text()
    guard = source.split("household_floor_authorised = bool(", 1)[1].split(
        "effective_min_soc = resolve_live_min_soc_on_grid(", 1
    )[0]
    for protected in (
        'ev_confirmed_unplugged',
        'ev_connected is False',
        'snapshot.ev_connected is False',
        'snapshot.ev_charging is False',
        'abs(float(snapshot.ev_power_kw)) <= 0.05',
        'not power_down_export_authorised',
        'not happy_hour_charge_authorised',
        'not pending_intelligent_ev_hold_active',
        'minimum_min_soc_on_grid <= 10.05',
        'control.desired_battery_export_power_kw <= 0.001',
    ):
        assert protected in guard
