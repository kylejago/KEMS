"""Learn future household capacity independently from instantaneous spikes."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from kems_core import Snapshot
from kems_core.discharge_slot_ledger import allocate_total_discharge_slots
from kems_core.learning import LearningEngine
from kems_core.physical_slot_capacity import allocate_physical_export_slots

from custom_components.kems.agile_physical_planning import apply_learned_house_profile

NOW = datetime(2026, 11, 24, 16, tzinfo=UTC)


def test_learned_profile_excludes_today_spike_and_missing_or_stale_days():
    records = [
        Snapshot(
            timestamp=NOW - timedelta(days=days) + timedelta(hours=1),
            house_load_kw=load,
        )
        for days, load in ((1, 1.0), (4, 1.4), (5, 1.2), (6, 15.0))
    ]
    records.extend(
        [
            Snapshot(timestamp=NOW, house_load_kw=12.0),
            Snapshot(
                timestamp=NOW - timedelta(days=7) + timedelta(hours=1),
                house_load_kw=20.0,
                stale_fields=("house_load_kw",),
            ),
        ]
    )
    learned = LearningEngine().analyse(records, NOW)
    assert learned.today_house_profile_date == "2026-11-24"
    assert learned.today_house_profile_kw[68] == pytest.approx(1.3)
    assert learned.today_house_profile_kw[64] is None


def test_capacity_profile_only_changes_future_with_verified_budget():
    segments = [
        {
            "start": NOW + timedelta(minutes=30 * index),
            "end": NOW + timedelta(minutes=30 * (index + 1)),
            "battery_kw": 7.0,
            "solar_kw": 0.0,
        }
        for index in range(2)
    ]
    learned = SimpleNamespace(
        ready=True,
        confidence=90.0,
        today_house_profile_date=NOW.date().isoformat(),
        today_house_profile_kw=(1.0,) * 96,
    )
    manager = SimpleNamespace(_kems_forecast_arbitrage_learned=learned)
    plan = {"physical_house_budget_evidence": {"available": True}}
    updated = apply_learned_house_profile(manager, segments, plan, now=NOW)
    assert "house_kw" not in updated[0]
    assert updated[1]["house_kw"] == 1.0
    assert "house_kw" not in segments[1]
    assert plan["future_house_capacity_profile"]["forecast_segments"] == 1
    assert apply_learned_house_profile(manager, segments, {}, now=NOW) is segments

    slots = [
        {"valid_from": s["start"], "valid_to": s["end"], "rate_pence": 25.0}
        for s in segments
    ]
    kwargs = {
        "slots": slots,
        "capacity_segments": updated,
        "now": NOW,
        "deadline": NOW + timedelta(hours=1),
        "house_kw": 4.0,
        "export_limit_kw": 7.0,
    }
    physical = allocate_physical_export_slots(desired_export_kwh=9.0, **kwargs)
    assert [row.capacity_kwh for row in physical.allocations] == [1.5, 3.0]
    ledger = allocate_total_discharge_slots(required_discharge_kwh=7.0, **kwargs)
    assert [row.export_capacity_kwh for row in ledger.allocations] == [1.5, 3.0]
