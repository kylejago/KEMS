from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path("custom_components/kems/foxess_control_backend.py")
_SESSION_PATH = Path("custom_components/kems/commissioning_session.py")
_SESSION_SPEC = importlib.util.spec_from_file_location(
    "kems_alpha878_commissioning_session",
    _SESSION_PATH,
)
assert _SESSION_SPEC is not None and _SESSION_SPEC.loader is not None
_SESSION_MODULE = importlib.util.module_from_spec(_SESSION_SPEC)
_SESSION_SPEC.loader.exec_module(_SESSION_MODULE)
collect_foxess_session_records = _SESSION_MODULE.collect_foxess_session_records


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


def test_commissioning_uses_only_fresh_foxess_proof_before_control_eligibility() -> (
    None
):
    source = Path("custom_components/kems/commissioning.py").read_text()
    backend = BACKEND.read_text()

    assert "collect_foxess_session_records" in source
    assert "assess_foxess_unit_contract" in source
    assert "assess_foxess_telemetry_stability" in source
    assert "assess_foxess_power_balance" in source
    assert '"foxess_unit_contract"' in source
    assert '"foxess_power_balance"' in source
    assert '"foxess_telemetry_proof_ready"' in source
    assert "coordinator._history" not in source
    assert '"ready_for_control": ready_for_control' in source
    assert "and not solar_only_commissioning" in source
    assert "and command_surface_ready" in source
    assert (
        "master_control_enabled=bool(coordinator.settings.control.control_enabled)"
        in backend
    )
    assert (
        "user_commissioned=bool(coordinator.settings.control.commissioned)" in backend
    )
    assert '"deliberate_force_discharge": "blocked_except_fixed_50w_grid_bias"' in backend
