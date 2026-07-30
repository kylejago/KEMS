from kems_core.ohme import OhmeState


def test_default_ohme_state() -> None:
    state = OhmeState()

    assert state.connected is False
    assert state.charging is False
    assert state.power_kw is None
