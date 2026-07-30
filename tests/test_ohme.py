"""Tests for the Ohme observation model."""

from kems_core.ohme import OhmeState


def test_ohme_defaults() -> None:
    """An empty Ohme observation should contain unknown values."""
    state = OhmeState()

    assert state.connected is None
    assert state.charging is None
    assert state.power_kw is None
    assert state.vehicle_soc is None
