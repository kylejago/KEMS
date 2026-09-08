"""Alpha9.15 current-slot Agile export stability regression contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from kems_core.forecast_path_scheduler import allocate_forecast_path_exports


def _slot(start: datetime, rate: float) -> dict[str, object]:
    return {
        "valid_from": start.isoformat(),
        "valid_to": (start + timedelta(minutes=30)).isoformat(),
        "rate_pence": rate,
        "label": start.strftime("%H:%M"),
    }


def _half_hour_segments(
    start: datetime,
    *,
    solar_kw: float,
    battery_kw: float,
) -> list[dict[str, object]]:
    return [
        {
            "start": (start + timedelta(minutes=5 * index)).isoformat(),
            "end": (start + timedelta(minutes=5 * (index + 1))).isoformat(),
            "solar_kw": solar_kw,
            "battery_kw": battery_kw,
        }
        for index in range(6)
    ]


def _allocate(
    *,
    now: datetime,
    current_rate: float,
    future_rates: tuple[float, ...],
    current_solar_kw: float = 0.0,
    current_battery_kw: float = 7.0,
    future_battery_kw: float = 4.0,
) -> object:
    slot_start = now.replace(minute=0, second=0, microsecond=0)
    slots = [_slot(slot_start, current_rate)]
    segments = _half_hour_segments(
        slot_start,
        solar_kw=current_solar_kw,
        battery_kw=current_battery_kw,
    )
    for index, rate in enumerate(future_rates, start=1):
        start = slot_start + timedelta(minutes=30 * index)
        slots.append(_slot(start, rate))
        segments.extend(
            _half_hour_segments(start, solar_kw=0.0, battery_kw=future_battery_kw)
        )

    return allocate_forecast_path_exports(
        slots=slots,
        capacity_segments=segments,
        now=now,
        deadline=slot_start + timedelta(minutes=30 * len(slots)),
        battery_capacity_kwh=10.0,
        soc_percent=50.0,
        target_soc_percent=20.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        max_charge_kw=7.0,
        house_kw=0.0,
        export_limit_kw=7.0,
        minimum_export_rate_pence=3.5,
        safety_headroom_kwh=3.5,
    )


def test_safety_headroom_never_demotes_higher_value_future_export() -> None:
    """The 3.5 kWh headroom heuristic must not create cheap current export."""
    start = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    plan = _allocate(now=start, current_rate=5.67, future_rates=(20.0, 19.0))

    assert plan.available is True
    assert plan.allocations[0].planned_battery_export_kwh == 0.0
    assert plan.allocations[1].planned_battery_export_kwh == pytest.approx(2.0, 0.001)
    assert plan.allocations[2].planned_battery_export_kwh == pytest.approx(1.0, 0.001)
    assert plan.minimum_soc_percent >= 20.0 - 1e-5


def test_low_value_current_slot_is_stable_across_coordinator_scans() -> None:
    """Advancing within the same cheap slot cannot flip it into deliberate export."""
    start = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    early = _allocate(
        now=start + timedelta(minutes=1),
        current_rate=5.67,
        future_rates=(20.0, 19.0),
    )
    later = _allocate(
        now=start + timedelta(minutes=10),
        current_rate=5.67,
        future_rates=(20.0, 19.0),
    )

    assert early.allocations[0].planned_battery_export_kwh == 0.0
    assert later.allocations[0].planned_battery_export_kwh == 0.0


def test_solar_storage_does_not_trigger_low_value_current_battery_export() -> None:
    """Do not recreate the live EXPO/CHARGE defect while better future slots exist."""
    start = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    plan = _allocate(
        now=start,
        current_rate=6.48,
        future_rates=(24.0, 23.0),
        current_solar_kw=4.0,
        current_battery_kw=3.0,
        future_battery_kw=6.0,
    )

    assert plan.forecast_solar_stored_kwh > 0.0
    assert plan.allocations[0].planned_battery_export_kwh == 0.0
    assert (
        sum(
            allocation.planned_battery_export_kwh for allocation in plan.allocations[1:]
        )
        >= 4.99
    )


def test_low_value_current_export_remains_allowed_when_better_capacity_is_full() -> (
    None
):
    """Price protection must not strand energy when the better future slot is full."""
    start = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    plan = _allocate(now=start, current_rate=7.72, future_rates=(20.0,))

    assert plan.allocations[1].planned_battery_export_kwh == pytest.approx(2.0, 0.001)
    assert plan.allocations[0].planned_battery_export_kwh == pytest.approx(1.0, 0.001)
    assert plan.ending_soc_percent == pytest.approx(20.0, abs=1e-5)
