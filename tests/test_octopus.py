"""Tests for the Octopus observation model."""

from kems_core.octopus import OctopusState


def test_octopus_defaults() -> None:
    """An empty Octopus observation should contain unknown values."""
    state = OctopusState()

    assert state.current_rate_pence is None
    assert state.next_rate_pence is None
    assert state.off_peak is None
    assert state.intelligent_slot is None
