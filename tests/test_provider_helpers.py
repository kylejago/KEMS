"""Tests for provider-independent Ohme and FoxESS helpers."""

from kems_core import calculate_battery_power_kw, interpret_charger_status


def test_ohme_status_is_interpreted() -> None:
    """The current Ohme enum status should drive connected/charging flags."""
    assert interpret_charger_status("charging") == (True, True)
    assert interpret_charger_status("plugged_in") == (True, False)
    assert interpret_charger_status("pending_approval") == (True, False)
    assert interpret_charger_status("unplugged") == (False, False)


def test_unknown_ohme_status_is_safe() -> None:
    """Unknown status values should not create false observations."""
    assert interpret_charger_status(None) == (None, None)
    assert interpret_charger_status("unavailable") == (None, None)
    assert interpret_charger_status("future_state") == (None, None)


def test_foxess_battery_power_can_be_derived() -> None:
    """FoxESS voltage and current can provide battery power when needed."""
    assert calculate_battery_power_kw(400.0, 10.0) == 4.0
    assert calculate_battery_power_kw(400.0, -10.0) == -4.0
    assert calculate_battery_power_kw(None, 10.0) is None
