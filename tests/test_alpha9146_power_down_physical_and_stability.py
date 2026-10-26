"""Alpha9.146 physical Power Down meter evidence and storage stability."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from kems_core.power_down_physical_evidence import (
    _observe_physical_grid,
    _physical_event_result,
)

from custom_components.kems.kems_core import PowerDownResult, Snapshot


def _pending() -> dict:
    return {
        "session_id": "7865",
        "session_start": "2026-10-26T18:00:00+00:00",
        "session_end": "2026-10-26T19:00:00+00:00",
        "planned_export_kwh": 4.631,
        "bonus_pence": 46.13,
    }


def _sample(at: datetime, *, export: float, joined: bool = True) -> Snapshot:
    return Snapshot(
        timestamp=at,
        saving_session_active=True,
        saving_session_joined=joined,
        grid_export_kw=export,
        grid_import_kw=0.0,
    )


def test_modelled_bonus_with_zero_meter_export_is_not_a_success() -> None:
    pending = _pending()
    start = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
    for n in range(60):
        at = start + timedelta(minutes=n)
        _observe_physical_grid(pending, _sample(at, export=0.0), at)
    physical = _physical_event_result(pending)
    assert physical["physical_export_verified"] is False
    assert physical["physical_grid_export_kwh"] == 0.0
    assert physical["physical_coverage_hours"] > 0.95
    assert physical["physical_evidence_status"] == "no_significant_physical_export"
    assert pending["planned_export_kwh"] == 4.631
    assert pending["bonus_pence"] == 46.13


def test_measured_delivery_requires_sustained_fresh_event_coverage() -> None:
    pending = _pending()
    start = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
    for n in range(60):
        at = start + timedelta(minutes=n)
        _observe_physical_grid(pending, _sample(at, export=2.0), at)
    physical = _physical_event_result(pending)
    assert physical["physical_export_verified"] is True
    assert 1.95 < physical["physical_grid_export_kwh"] < 2.0
    assert physical["supplier_settled"] is False


def test_event_gap_and_unjoined_meter_samples_do_not_invent_energy() -> None:
    pending = _pending()
    start = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
    _observe_physical_grid(pending, _sample(start, export=7.0), start)
    at = start + timedelta(minutes=8)
    _observe_physical_grid(pending, _sample(at, export=7.0), at)
    at = start + timedelta(minutes=9)
    _observe_physical_grid(pending, _sample(at, export=7.0, joined=False), at)
    physical = _physical_event_result(pending)
    assert physical["physical_export_verified"] is None
    assert physical["physical_grid_export_kwh"] == 0.0
    assert physical["physical_coverage_hours"] == 0.0


def test_ambiguous_bidirectional_meter_and_stale_grid_readings_excluded() -> None:
    pending = _pending()
    start = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
    _observe_physical_grid(pending, _sample(start, export=4.0), start)
    at = start + timedelta(minutes=1)
    ambiguous = _sample(at, export=4.0)
    ambiguous.grid_import_kw = 2.0
    _observe_physical_grid(pending, ambiguous, at)
    assert _physical_event_result(pending)["physical_coverage_hours"] == 0.0
    assert _physical_event_result(pending)["physical_export_verified"] is None


def test_legacy_model_only_success_reclassified_as_unverified() -> None:
    old = {
        "available": True,
        "session_id": "7865",
        "active_samples_observed": 55,
        "completed_successfully": True,
        "completion_reason": "completed",
        "planned_export_kwh": 4.631,
        "bonus_pence": 46.13,
    }
    result = PowerDownResult.from_dict(old)
    assert result.completed_successfully is None
    assert result.completion_reason == "historical_physical_evidence_unavailable"
    assert result.physical_grid_export_kwh is None
    assert result.bonus_pence == 46.13
    assert result.supplier_settled is False


def test_history_write_avoidance_does_not_touch_control_dispatch() -> None:
    root = Path(__file__).parents[1] / "custom_components" / "kems"
    patch = (root / "alpha951_power_down_post_event.py").read_text()
    assert "if payload == getattr(self, " in patch
    assert "await self._store.async_save(payload)" in patch
    assert "modelled estimate; not supplier settled" in patch
    assert "confirmed_supplier_credit_today_pence" in patch
    assert "async_call(" not in patch
    assert "foxess_modbus" not in patch


def test_historical_cache_no_longer_allocates_recursively_copied_inputs() -> None:
    root = Path(__file__).parents[1] / "custom_components" / "kems"
    source = (root / "kems_core/agile_historical_replay_cache.py").read_text()
    assert "binary_sha256_only_per_historical_day" in source
    assert "self._fingerprint(inputs)" in source
    assert "_capture_snapshot(" not in source
    assert "_unchanged_snapshot(" not in source
