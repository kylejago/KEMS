"""Alpha9.223: independently sampled FoxESS counters and honest provenance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from kems_core.operational_diagnostic_probes import (
    foxess_import_counter_candidate_probe,
)

ROOT = Path(__file__).resolve().parents[1]
COORDINATOR = ROOT / "custom_components" / "kems" / "coordinator.py"


def _state(value: str, when: datetime):
    return SimpleNamespace(
        state=value,
        attributes={"unit_of_measurement": "kWh", "state_class": "total"},
        last_reported=when,
        last_updated=when,
    )


def _entry():
    return SimpleNamespace(
        device_id="foxess-device",
        config_entry_id="foxess-entry",
        disabled_by=None,
    )


def test_optional_counter_observation_not_gated_by_history_recorder() -> None:
    """A source counter may report between accepted sampled-history records."""
    text = COORDINATOR.read_text(encoding="utf-8")
    assert "if await self._history.async_record(snapshot):" not in text
    assert (
        "await self._history.async_record(snapshot)\n"
        "            # The independent cumulative-counter evidence"
    ) in text
    assert "self._counter_evidence.observe(now=snapshot.timestamp)" in text


def test_counter_probe_discloses_freshness_but_never_authorises_backfill() -> None:
    now = datetime(2026, 11, 18, 0, tzinfo=UTC)
    fresh = _state("2075.2", now - timedelta(seconds=60))
    stale = _state("57.8", now - timedelta(seconds=181))
    probe = foxess_import_counter_candidate_probe(
        source_entity_id="sensor.kh7_grid_consumption",
        source_registry=_entry(),
        candidates={
            "lifetime_total": (_entry(), fresh),
            "daily_total": (_entry(), stale),
        },
        now=now,
    )
    first = probe["candidates"]["lifetime_total"]
    second = probe["candidates"]["daily_total"]
    assert first["fresh_report_for_evidence_capture"] is True
    assert second["fresh_report_for_evidence_capture"] is False
    assert first["candidate_status"] == "single_reading_only_unverified"
    assert probe["counter_capture_requires_fresh_report_seconds"] == 180
    assert probe["counter_source_approved"] is False
    assert probe["long_gap_recovery_enabled"] is False
    assert first["restart_delta_usable"] is False
