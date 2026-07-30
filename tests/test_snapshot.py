"""Tests for the Snapshot model."""

from datetime import datetime

from kems_core.snapshot import Snapshot


def test_snapshot_defaults() -> None:
    """A new snapshot should be timezone-aware and otherwise empty."""
    snapshot = Snapshot()

    assert isinstance(snapshot.timestamp, datetime)
    assert snapshot.timestamp.tzinfo is not None
    assert snapshot.current_import_rate is None
    assert snapshot.next_import_rate is None
    assert snapshot.off_peak is None
    assert snapshot.intelligent_slot is None
    assert snapshot.ev_connected is None
    assert snapshot.ev_charging is None
