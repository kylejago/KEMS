"""Tests for KEMS domain models."""

from datetime import UTC, datetime

from kems_core import Snapshot


def test_snapshot_round_trip() -> None:
    """Snapshots should survive JSON-compatible persistence."""
    snapshot = Snapshot(
        timestamp=datetime(2026, 7, 30, 21, 0, tzinfo=UTC),
        current_import_rate=28.3,
        house_load_kw=1.25,
        off_peak=False,
    )

    restored = Snapshot.from_dict(snapshot.to_dict())

    assert restored == snapshot


def test_extra_intelligent_slot_requires_ohme_charging_confirmation() -> None:
    """Extra cheap slots are confirmed by Octopus and active Ohme charging."""
    assert Snapshot(off_peak=True).cheap_period_confirmed is True
    assert (
        Snapshot(
            off_peak=False,
            intelligent_slot=True,
            ev_charging=True,
        ).cheap_period_confirmed
        is True
    )
    assert (
        Snapshot(
            off_peak=False,
            intelligent_slot=True,
            ev_charging=False,
        ).cheap_period_confirmed
        is False
    )
