"""Regression coverage for Agile Smart Export Home Assistant history backfill."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
BACKFILL = ROOT / "custom_components" / "kems" / "agile_history_backfill.py"
COORDINATOR = ROOT / "custom_components" / "kems" / "coordinator.py"
DIAGNOSTICS = ROOT / "custom_components" / "kems" / "diagnostics.py"
REPORTING = ROOT / "custom_components" / "kems" / "agile_smart_export_reporting.py"


def test_backfill_uses_supported_recorder_service_not_database_access() -> None:
    """Historical replay must not couple KEMS to Recorder's database schema."""
    content = BACKFILL.read_text(encoding="utf-8")
    assert '"recorder",\n                "get_statistics"' in content
    assert '"period": "hour"' in content
    assert '"types": ["mean", "state"]' in content
    assert "return_response=True" in content
    assert "sqlalchemy" not in content.lower()
    assert "session_scope" not in content


def test_backfill_is_fidelity_labelled_and_never_invents_bonus_slots() -> None:
    """Recovered days must clearly disclose the lower-fidelity assumptions."""
    content = BACKFILL.read_text(encoding="utf-8")
    assert "TARGET_DAYS = 365" in content
    assert "MIN_DAY_COVERAGE = 0.75" in content
    assert 'intelligent_slot=False' in content
    assert "historical Intelligent bonus slots are not invented" in content
    assert "historical KEMS forecast annotations are unavailable" in content
    assert '"authoritative_native_365"' in content


def test_backfill_prefers_native_kems_days() -> None:
    """Hourly HA history must never replace native KEMS observations."""
    content = BACKFILL.read_text(encoding="utf-8")
    assert "def _merge_native_and_backfill" in content
    assert "if item.timestamp.astimezone(LONDON).date() not in native_days" in content


def test_backfill_handles_uk_dst_day_lengths() -> None:
    """Coverage gating must allow 23/24/25-hour UK local days."""
    content = BACKFILL.read_text(encoding="utf-8")
    assert "def _expected_hours" in content
    assert "day + timedelta(days=1)" in content
    assert "(end - start).total_seconds() // 3600" in content


def test_coordinator_uses_backfill_only_for_agile_replay() -> None:
    """Normal KEMS learning stays native while Agile receives merged history."""
    content = COORDINATOR.read_text(encoding="utf-8")
    assert "AgileHistoryBackfill" in content
    assert "max(settings.history_days, 365)" in content
    assert "agile_records = await self._agile_history_backfill.async_records" in content
    assert "records=agile_records" in content
    assert "learned = self._learning.analyse(records, now)" in content
    assert "simulation = self._simulation.simulate_today(\n                records," in content


def test_backfill_quality_is_visible_in_dashboard_and_diagnostics() -> None:
    """Users must be able to see native/backfilled/insufficient day counts."""
    reporting = REPORTING.read_text(encoding="utf-8")
    diagnostics = DIAGNOSTICS.read_text(encoding="utf-8")
    assert "sensor.kems_agile_history_backfill" in reporting
    assert "Native KEMS days" in reporting
    assert "HA statistics backfilled days" in reporting
    assert "Insufficient historical days" in reporting
    assert '"agile_history_backfill": coordinator.agile_history_backfill_state' in diagnostics
