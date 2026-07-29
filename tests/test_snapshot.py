from datetime import datetime

from kems_core.snapshot import Snapshot


def test_snapshot_creation() -> None:
    snapshot = Snapshot(timestamp=datetime.now())

    assert snapshot.electricity_rate is None
    assert snapshot.ev_power_kw is None
