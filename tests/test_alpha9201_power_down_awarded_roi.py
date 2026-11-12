"""Power Down ROI: supplier-awarded points replace, never stack with estimates."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from custom_components.kems.roi_reward_recorder import ROIRewardRecorder


class FakeStore:
    def __init__(self):
        self.saved = []

    async def async_save(self, payload):
        self.saved.append(payload)


def _event(
    *,
    identifier: str = "8447",
    physical: bool = True,
    completed: bool = True,
    bonus: float | None = 56.48,
    reduction: float | None = 5.511,
):
    return SimpleNamespace(
        available=True,
        session_id=identifier,
        session_start=datetime(2026, 11, 12, 17, tzinfo=UTC),
        session_end=datetime(2026, 11, 12, 18, tzinfo=UTC),
        completed_successfully=completed,
        physical_export_verified=physical,
        bonus_pence=bonus,
        rewardable_reduction_kwh=reduction,
        fixed_export_income_pence=57.20,
        physical_grid_export_kwh=4.109,
        reward_evidence_status="modelled_reward_inputs_observed",
    )


def _joined(points, *, identifier=8447, end="2026-11-12T18:00:00Z"):
    return {
        "id": identifier,
        "start": "2026-11-12T17:00:00Z",
        "end": end,
        "octopoints_per_kwh": 82,
        "rewarded_octopoints": points,
    }


def _recorder():
    item = ROIRewardRecorder.__new__(ROIRewardRecorder)
    item._store = FakeStore()
    item._happy_hours = {}
    item._power_downs = {}
    item._joined_happy_hours = {}
    return item


def _observe(recorder, events, joined=()):
    asyncio.run(recorder.async_observe([], events, supplier_power_down_events=joined))


def test_awarded_points_replace_model_estimate_and_count_once() -> None:
    recorder = _recorder()
    event = _event()
    _observe(recorder, [event])
    assert recorder._power_downs["8447"]["pence"] == 56.48
    assert recorder._power_downs["8447"]["supplier_settled"] is False

    _observe(recorder, [event], [_joined(600)])
    saved = recorder._power_downs["8447"]
    assert saved["pence"] == 75.0  # 800 Octopoints = £1.
    assert saved["awarded_octopoints"] == 600
    assert saved["basis"] == "supplier_awarded_octopoints"
    assert saved["supplier_settled"] is True

    now = datetime(2026, 11, 12, 19, tzinfo=UTC)
    totals = recorder.totals(now, date(2026, 9, 12))
    assert totals["power_down"] == 75.0
    assert totals["total"] == 75.0
    assert totals["unsettled"] == 0.0
    assert totals["supplier_awarded"] == 75.0
    assert totals["meter_supported"] == 0.0

    audit = recorder.audit(now, date(2026, 9, 12), events=[event])
    assert audit["included_power_down_pence"] == 75.0
    assert audit["supplier_awarded_power_down_pence"] == 75.0
    assert audit["supplier_settlement_available"] is True
    row = audit["entries"][0]
    assert row["supplier_status"] == "settled"
    assert row["awarded_octopoints"] == 600
    assert row["agile_export_income_already_counted"] is True
    assert row["modelled_agile_export_income_pence"] == 57.2

    stored_before = len(recorder._store.saved)
    _observe(recorder, [event], [_joined(600)])
    _observe(recorder, [event])  # Historical provider feed may expire.
    assert len(recorder._store.saved) == stored_before
    assert recorder._power_downs["8447"] == saved


@pytest.mark.parametrize(
    "joined",
    [
        _joined(None),
        _joined(0),
        _joined(False),
        _joined(82.5),
        _joined(-1),
        _joined(2_000_001),
        _joined(800, identifier=8448),
        _joined(800, end="2026-11-12T18:30:00Z"),
        {
            "id": 8447,
            "start": "2026-11-12T17:00:00",
            "end": "2026-11-12T18:00:00Z",
            "rewarded_octopoints": 800,
        },
    ],
)
def test_incomplete_or_unmatched_supplier_award_is_not_invented(joined) -> None:
    recorder = _recorder()
    event = _event(bonus=None, reduction=None)
    _observe(recorder, [event], [joined])
    assert recorder._power_downs == {}


@pytest.mark.parametrize("physical, completed", [(False, True), (True, False)])
def test_unverified_kems_event_is_not_mistaken_for_roi_supplier_award(
    physical: bool, completed: bool
) -> None:
    recorder = _recorder()
    _observe(
        recorder,
        [_event(physical=physical, completed=completed)],
        [_joined(800)],
    )
    assert recorder._power_downs == {}


def test_missing_octopus_rate_baseline_and_award_remains_pending() -> None:
    recorder = _recorder()
    event = _event(bonus=None, reduction=None)
    _observe(recorder, [event], [_joined(None)])
    audit = recorder.audit(
        datetime(2026, 11, 12, 19, tzinfo=UTC),
        date(2026, 9, 12),
        events=[event],
    )
    assert audit["historical_coverage"]["power_down_events_pending_evidence"] == 1
    assert audit["included_power_down_pence"] == 0.0
    assert audit["supplier_settlement_available"] is False
    assert audit["entries"][0]["status"] == "pending_bonus_or_baseline_evidence"
