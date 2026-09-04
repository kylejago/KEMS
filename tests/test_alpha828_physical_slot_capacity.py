"""Regression coverage for Alpha8.28 physical Agile slot capacity."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kems_core.physical_slot_capacity import allocate_physical_export_slots

ROOT = Path(__file__).parents[1]


def _slot(start: datetime, rate: float) -> dict[str, object]:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "rate_pence": rate,
        "label": start.strftime("%H:%M"),
    }


def _segments(
    start: datetime,
    *,
    solar_kw: float,
    battery_kw: float,
    count: int = 6,
) -> list[dict[str, object]]:
    return [
        {
            "start": (start + timedelta(minutes=5 * index)).isoformat(),
            "end": (start + timedelta(minutes=5 * (index + 1))).isoformat(),
            "solar_kw": solar_kw,
            "battery_kw": battery_kw,
        }
        for index in range(count)
    ]


def test_future_slot_does_not_claim_full_3_5_kwh_when_solar_uses_inverter() -> None:
    start = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)
    plan = allocate_physical_export_slots(
        slots=[_slot(start, 30.0)],
        capacity_segments=_segments(start, solar_kw=3.0, battery_kw=4.0),
        now=start,
        deadline=start + timedelta(hours=1),
        desired_export_kwh=3.5,
        house_kw=1.0,
        export_limit_kw=7.0,
    )

    assert plan.total_capacity_kwh == 2.0
    assert plan.allocated_kwh == 2.0
    assert plan.unallocated_kwh == 1.5
    assert plan.allocations[0].capacity_kwh == 2.0


def test_house_load_reduces_export_but_still_counts_as_battery_discharge() -> None:
    start = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)
    plan = allocate_physical_export_slots(
        slots=[_slot(start, 30.0)],
        capacity_segments=_segments(start, solar_kw=0.0, battery_kw=7.0),
        now=start,
        deadline=start + timedelta(hours=1),
        desired_export_kwh=3.5,
        house_kw=1.5,
        export_limit_kw=7.0,
    )

    assert plan.total_capacity_kwh == 2.75
    assert plan.allocated_kwh == 2.75
    assert plan.unallocated_kwh == 0.75


def test_price_ranking_uses_each_slots_real_capacity() -> None:
    first = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)
    second = first + timedelta(minutes=30)
    segments = _segments(first, solar_kw=3.0, battery_kw=4.0)
    segments += _segments(second, solar_kw=0.0, battery_kw=7.0)
    plan = allocate_physical_export_slots(
        slots=[_slot(first, 40.0), _slot(second, 20.0)],
        capacity_segments=segments,
        now=first,
        deadline=second + timedelta(minutes=30),
        desired_export_kwh=4.0,
        house_kw=1.0,
        export_limit_kw=7.0,
    )

    assert plan.allocations[0].allocated_kwh == 2.0
    assert plan.allocations[1].allocated_kwh == 2.0
    assert plan.allocated_kwh == 4.0


def test_power_down_window_is_not_reused_for_ordinary_agile_export() -> None:
    first = datetime(2026, 8, 26, 16, 30, tzinfo=UTC)
    second = first + timedelta(minutes=30)
    segments = _segments(first, solar_kw=0.0, battery_kw=7.0)
    segments += _segments(second, solar_kw=0.0, battery_kw=7.0)
    plan = allocate_physical_export_slots(
        slots=[_slot(first, 50.0), _slot(second, 20.0)],
        capacity_segments=segments,
        now=first,
        deadline=second + timedelta(minutes=30),
        desired_export_kwh=3.0,
        house_kw=1.0,
        export_limit_kw=7.0,
        excluded_windows=((first, first + timedelta(minutes=30)),),
    )

    assert len(plan.allocations) == 1
    assert plan.allocations[0].valid_from == second
    assert plan.allocations[0].allocated_kwh == 3.0


def test_current_partial_slot_keeps_original_settlement_start() -> None:
    start = datetime(2026, 8, 26, 15, 0, tzinfo=UTC)
    now = start + timedelta(minutes=10)
    segments = _segments(now, solar_kw=0.0, battery_kw=7.0, count=4)
    plan = allocate_physical_export_slots(
        slots=[_slot(start, 30.0)],
        capacity_segments=segments,
        now=now,
        deadline=start + timedelta(minutes=30),
        desired_export_kwh=3.5,
        house_kw=1.0,
        export_limit_kw=7.0,
    )

    assert plan.allocations[0].valid_from == start
    assert plan.allocations[0].valid_to == start + timedelta(minutes=30)
    assert plan.allocations[0].capacity_kwh == 2.0


def test_alpha828_runtime_uses_deadline_capacity_and_preserves_hardware_block() -> None:
    runtime = (ROOT / "custom_components/kems/agile_solar_net_demand.py").read_text()
    compat = (ROOT / "custom_components/kems/agile_alpha7_compat.py").read_text()

    assert "deadline_runtime._capacity_segments" in runtime
    assert "allocate_physical_export_slots" in runtime
    assert '"physical_slot_capacity_reconciled": True' in runtime
    assert '"hardware_writes": "blocked"' in runtime
    assert compat.rfind("install_solar_net_demand") > compat.find(
        "install_runtime_reconciliation"
    )


def test_alpha828_version_and_release_contract_remains_successor_safe() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())

    version = manifest["version"]
    assert version.startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    assert int(version.rsplit(".", 1)[1]) >= 28
    assert "kems_core" in bundle["maintenance"]["affected_components"]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
