"""Tests for provider-independent Ohme and FoxESS helpers."""

from kems_core import (
    calculate_battery_power_kw,
    interpret_charger_status,
    normalise_grid_power,
)


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


def test_grid_power_normalisation_never_exposes_negative_import_or_export() -> None:
    """Signed and duplicate sources should become clear positive magnitudes."""
    importing = normalise_grid_power(0.573, None)
    assert importing.import_kw == 0.573
    assert importing.export_kw == 0.0

    exporting = normalise_grid_power(-2.5, None)
    assert exporting.import_kw == 0.0
    assert exporting.export_kw == 2.5

    duplicate = normalise_grid_power(-3.2, -3.2)
    assert duplicate.import_kw == 0.0
    assert duplicate.export_kw == 3.2
    assert duplicate.mode == "duplicate_signed_source_export"

    separate = normalise_grid_power(1.1, 0.4)
    assert separate.import_kw == 1.1
    assert separate.export_kw == 0.4
