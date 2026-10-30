"""Alpha9.163 household-only FoxESS MinSOC regression tests."""
from custom_components.kems.kems_core.control_write_authority import (
    FoxESSControlDecision, resolve_live_min_soc_on_grid,
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
    assert resolve_live_min_soc_on_grid(
        _decision(), cheap_period_confirmed=False,
        previous_min_soc_on_grid=15.0,
    ) == 10.0


def test_other_noncheap_floor_preserves_original_baseline():
    assert resolve_live_min_soc_on_grid(
        _decision(requested=15.0), cheap_period_confirmed=False,
        previous_min_soc_on_grid=15.0,
    ) == 15.0


def test_ev_hold_does_not_drop_to_10_percent():
    assert resolve_live_min_soc_on_grid(
        _decision(requested=100.0), cheap_period_confirmed=False,
        previous_min_soc_on_grid=15.0,
        pending_intelligent_ev_hold_active=True,
    ) == 100.0


def test_cheap_period_keeps_force_charge_min_soc():
    assert resolve_live_min_soc_on_grid(
        _decision(action="force_charge", requested=15.0),
        cheap_period_confirmed=True, previous_min_soc_on_grid=15.0,
    ) == 15.0
