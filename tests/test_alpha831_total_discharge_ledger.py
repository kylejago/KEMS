"""Regression coverage for Alpha8.31 total-discharge deadline planning."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kems_core.discharge_slot_ledger import (
    allocate_total_discharge_slots,
    required_total_discharge_kwh,
)

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
    count: int,
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


def test_uploaded_527_percent_case_requires_22_887_kwh_total_discharge() -> None:
    """Lock the exact Alpha8.30 failure arithmetic from the uploaded diagnostic."""
    required = required_total_discharge_kwh(
        battery_capacity_kwh=56.42,
        soc_percent=52.7,
        target_soc_percent=10.0,
        discharge_efficiency=0.95,
    )

    assert required == 22.887


def test_house_reserve_is_not_assumed_to_be_guaranteed_future_discharge() -> None:
    """The ledger allocates the SOC obligation, not obligation minus house reserve."""
    start = datetime(2026, 8, 26, 19, 0, tzinfo=UTC)
    deadline = start + timedelta(hours=3, minutes=30)
    slots = [_slot(start + timedelta(minutes=30 * index), 20.0 - index) for index in range(7)]
    plan = allocate_total_discharge_slots(
        slots=slots,
        capacity_segments=_segments(
            start,
            solar_kw=0.0,
            battery_kw=7.0,
            count=42,
        ),
        now=start,
        deadline=deadline,
        required_discharge_kwh=22.887,
        house_kw=0.991,
        export_limit_kw=7.0,
        safety_headroom_kwh=3.5,
    )

    assert plan.allocated_total_discharge_kwh == 22.887
    assert plan.unallocated_total_discharge_kwh == 0.0
    assert plan.planned_house_battery_kwh > 0.0
    # Alpha8.30 planned only 18.064 kWh because the 4.826 kWh protected-house
    # reserve was treated as if it would definitely discharge. Alpha8.31 must
    # schedule enough export/house split to cover the full SOC obligation.
    assert plan.planned_battery_export_kwh > 18.064
    assert round(
        plan.planned_house_battery_kwh + plan.planned_battery_export_kwh,
        3,
    ) == 22.887


def test_safety_headroom_forces_earlier_total_discharge_before_deadline_cliff() -> None:
    start = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)
    second = start + timedelta(minutes=30)
    deadline = second + timedelta(minutes=30)
    plan = allocate_total_discharge_slots(
        slots=[_slot(start, 10.0), _slot(second, 20.0)],
        capacity_segments=_segments(
            start,
            solar_kw=0.0,
            battery_kw=7.0,
            count=12,
        ),
        now=start,
        deadline=deadline,
        required_discharge_kwh=4.0,
        house_kw=0.0,
        export_limit_kw=7.0,
        safety_headroom_kwh=3.5,
    )

    assert plan.required_current_total_discharge_kwh == 3.5
    assert plan.allocations[0].planned_total_discharge_kwh == 3.5
    assert plan.allocations[1].planned_total_discharge_kwh == 0.5


def test_slot_starting_at_cheap_deadline_is_never_discharge_capacity() -> None:
    start = datetime(2026, 8, 26, 21, 30, tzinfo=UTC)
    deadline = start + timedelta(minutes=30)
    cheap_start = deadline
    plan = allocate_total_discharge_slots(
        slots=[_slot(start, 10.0), _slot(cheap_start, 100.0)],
        capacity_segments=_segments(
            start,
            solar_kw=0.0,
            battery_kw=7.0,
            count=6,
        ),
        now=start,
        deadline=deadline,
        required_discharge_kwh=3.0,
        house_kw=0.0,
        export_limit_kw=7.0,
    )

    assert len(plan.allocations) == 1
    assert plan.allocations[0].valid_from == start
    assert plan.allocations[0].planned_total_discharge_kwh == 3.0


def test_runtime_uses_total_ledger_and_marks_cheap_boundary_charge_only() -> None:
    runtime = (ROOT / "custom_components/kems/agile_total_discharge_ledger.py").read_text()
    compat = (ROOT / "custom_components/kems/agile_alpha7_compat.py").read_text()

    assert "deadline_runtime._capacity_segments" in runtime
    assert "required_total_discharge_kwh(" in runtime
    assert "legacy_reserve_limited_exportable_battery_energy_kwh" in runtime
    assert '"planned_total_battery_discharge_kwh"' in runtime
    assert "_current_total_discharge_targets" in runtime
    assert "current.planned_total_discharge_kwh / remaining_hours" in runtime
    assert "_enforce_cheap_boundary" in runtime
    assert '"cheap charge — overnight window"' in runtime
    assert '"hardware_writes": "blocked"' in runtime
    assert compat.rfind("install_total_discharge_ledger") > compat.rfind(
        "install_solar_net_demand"
    )


def test_alpha831_version_and_release_scope() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())

    assert manifest["version"] == "0.8.0-alpha8.31"
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert "total battery-discharge ledger" in bundle["maintenance"]["reason"]
    assert "23:30 cheap-start boundary" in bundle["maintenance"]["reason"]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
