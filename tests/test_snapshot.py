"""Tests for the Snapshot model."""

from datetime import datetime

from kems_core.snapshot import Snapshot


def test_snapshot_creation() -> None:
    """Ensure a snapshot has the expected default values."""

    snapshot = Snapshot(timestamp=datetime.now())

    # Electricity
    assert snapshot.current_import_rate is None
    assert snapshot.next_import_rate is None
    assert snapshot.off_peak is None
    assert snapshot.intelligent_slot is None
    assert snapshot.next_offpeak_start is None
    assert snapshot.offpeak_end is None

    # EV
    assert snapshot.ev_connected is None
    assert snapshot.ev_charging is None
    assert snapshot.ev_power_kw is None
    assert snapshot.ev_soc is None

    # House
    assert snapshot.house_load_kw is None

    # Battery
    assert snapshot.battery_soc is None
    assert snapshot.battery_power_kw is None

    # Solar
    assert snapshot.solar_power_kw is None

    # Grid
    assert snapshot.grid_import_kw is None
    assert snapshot.grid_export_kw is None
