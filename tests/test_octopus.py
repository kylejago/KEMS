from kems_core.octopus import OctopusState


def test_octopus_defaults() -> None:
    state = OctopusState()

    assert state.current_rate is None
    assert state.next_rate is None
    assert state.off_peak is False
