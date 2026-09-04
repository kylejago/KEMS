from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from custom_components.kems.commissioning_session import (
    collect_foxess_session_records,
)


def _snapshot(at: datetime):
    return SimpleNamespace(timestamp=at)


def test_fresh_session_records_each_timestamp_once() -> None:
    owner = SimpleNamespace()
    signature = (("battery_soc", "sensor.soc|%"),)
    start = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)

    records, metadata = collect_foxess_session_records(
        owner,
        source_signature=signature,
        snapshot=_snapshot(start),
        ready=True,
    )
    assert len(records) == 1
    assert metadata["persistent"] is False
    assert metadata["scope"] == "current coordinator session only"
    assert metadata["reset_reason"] == "session_started"

    records, _ = collect_foxess_session_records(
        owner,
        source_signature=signature,
        snapshot=_snapshot(start),
        ready=True,
    )
    assert len(records) == 1

    records, _ = collect_foxess_session_records(
        owner,
        source_signature=signature,
        snapshot=_snapshot(start + timedelta(minutes=1)),
        ready=True,
    )
    assert len(records) == 2


def test_source_or_unit_signature_change_resets_evidence() -> None:
    owner = SimpleNamespace()
    start = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)
    first_signature = (("grid_import_kw", "sensor.grid|kW"),)
    changed_signature = (("grid_import_kw", "sensor.grid|W"),)

    collect_foxess_session_records(
        owner,
        source_signature=first_signature,
        snapshot=_snapshot(start),
        ready=True,
    )
    records, metadata = collect_foxess_session_records(
        owner,
        source_signature=changed_signature,
        snapshot=_snapshot(start + timedelta(minutes=1)),
        ready=True,
    )

    assert len(records) == 1
    assert records[0].timestamp == start + timedelta(minutes=1)
    assert metadata["reset_reason"] == "source_signature_changed"


def test_lost_mapping_gate_clears_evidence_and_restart_inherits_nothing() -> None:
    owner = SimpleNamespace()
    signature = (("solar_power_kw", "sensor.pv|kW"),)
    start = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)

    collect_foxess_session_records(
        owner,
        source_signature=signature,
        snapshot=_snapshot(start),
        ready=True,
    )
    records, metadata = collect_foxess_session_records(
        owner,
        source_signature=signature,
        snapshot=_snapshot(start + timedelta(minutes=1)),
        ready=False,
    )
    assert records == ()
    assert metadata["reset_reason"] == "physical_sources_not_ready"

    restarted_owner = SimpleNamespace()
    records, metadata = collect_foxess_session_records(
        restarted_owner,
        source_signature=signature,
        snapshot=_snapshot(start + timedelta(minutes=2)),
        ready=True,
    )
    assert len(records) == 1
    assert metadata["reset_reason"] == "session_started"


def test_commissioning_uses_only_fresh_foxess_proof_and_keeps_writes_blocked() -> None:
    source = Path("custom_components/kems/commissioning.py").read_text()

    assert "collect_foxess_session_records" in source
    assert "assess_foxess_unit_contract" in source
    assert "assess_foxess_telemetry_stability" in source
    assert "assess_foxess_power_balance" in source
    assert '"foxess_unit_contract"' in source
    assert '"foxess_power_balance"' in source
    assert '"foxess_telemetry_proof_ready"' in source
    assert "coordinator._history" not in source
    assert '"real_hardware_writes": "blocked"' in source
    assert '"ready_for_control": False' in source
    assert '"maximum_allowed_stage": "shadow"' in source
