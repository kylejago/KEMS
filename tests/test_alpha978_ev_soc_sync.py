"""Alpha9.78 EV SOC sync regression tests."""

from custom_components.kems.ev_soc_sync import ev_soc_sync_write_decision


def test_ev_soc_sync_write_decision_is_narrow_and_fail_closed() -> None:
    base = dict(
        emergency_stop=False,
        connected=True,
        source_soc=85.0,
        target_soc=80.0,
        cooldown_active=False,
    )
    assert ev_soc_sync_write_decision(enabled=False, **base)[:2] == (False, "disabled")
    assert ev_soc_sync_write_decision(
        enabled=True,
        emergency_stop=True,
        connected=True,
        source_soc=85.0,
        target_soc=80.0,
        cooldown_active=False,
    )[:2] == (False, "blocked")
    assert ev_soc_sync_write_decision(
        enabled=True,
        emergency_stop=False,
        connected=False,
        source_soc=85.0,
        target_soc=80.0,
        cooldown_active=False,
    )[:2] == (False, "idle")
    assert ev_soc_sync_write_decision(
        enabled=True,
        emergency_stop=False,
        connected=True,
        source_soc=None,
        target_soc=80.0,
        cooldown_active=False,
    )[:2] == (False, "waiting_source")
    assert ev_soc_sync_write_decision(
        enabled=True,
        emergency_stop=False,
        connected=True,
        source_soc=85.0,
        target_soc=85.0,
        cooldown_active=False,
    )[:2] == (False, "matched")
    assert ev_soc_sync_write_decision(
        enabled=True,
        emergency_stop=False,
        connected=True,
        source_soc=85.0,
        target_soc=80.0,
        cooldown_active=True,
    )[:2] == (False, "cooldown")
    assert ev_soc_sync_write_decision(enabled=True, **base)[:2] == (True, "write")
