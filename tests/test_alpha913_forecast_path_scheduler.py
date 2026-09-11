"""Regression coverage for Alpha9.13 forecast-aware Agile export timing."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from kems_core.forecast_path_scheduler import allocate_forecast_path_exports

ROOT = Path(__file__).parents[1]


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


def test_forecast_path_avoids_9p_export_when_higher_value_path_is_feasible() -> None:
    """Future solar may refill earlier export, but cheap midday battery export loses."""
    start = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    slots = [
        _slot(start, 18.0),
        _slot(start + timedelta(minutes=30), 9.8),
        _slot(start + timedelta(hours=1), 9.7),
        _slot(start + timedelta(hours=1, minutes=30), 22.0),
        _slot(start + timedelta(hours=2), 21.0),
    ]
    segments = [
        *_half_hour_segments(start, solar_kw=0.0, battery_kw=7.0),
        *_half_hour_segments(
            start + timedelta(minutes=30), solar_kw=4.0, battery_kw=3.0
        ),
        *_half_hour_segments(start + timedelta(hours=1), solar_kw=4.0, battery_kw=3.0),
        *_half_hour_segments(
            start + timedelta(hours=1, minutes=30), solar_kw=0.0, battery_kw=4.0
        ),
        *_half_hour_segments(start + timedelta(hours=2), solar_kw=0.0, battery_kw=4.0),
    ]

    plan = allocate_forecast_path_exports(
        slots=slots,
        capacity_segments=segments,
        now=start,
        deadline=start + timedelta(hours=2, minutes=30),
        battery_capacity_kwh=10.0,
        soc_percent=50.0,
        target_soc_percent=20.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        max_charge_kw=7.0,
        house_kw=0.0,
        export_limit_kw=7.0,
        minimum_export_rate_pence=3.5,
    )

    assert plan.available is True
    allocations = {
        item.rate_pence: item.planned_battery_export_kwh for item in plan.allocations
    }
    assert allocations[18.0] >= 2.99
    assert allocations[9.8] == 0.0
    assert allocations[9.7] == 0.0
    assert allocations[22.0] == 2.0
    assert allocations[21.0] == 2.0
    assert plan.ending_soc_percent == pytest.approx(20.0, abs=1e-5)
    assert plan.minimum_soc_percent >= 20.0 - 1e-5
    assert plan.forecast_solar_stored_kwh == 4.0


def test_forecast_solar_is_never_borrowed_before_it_arrives() -> None:
    """An expensive early slot can spend only energy physically stored at that time."""
    start = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
    slots = [
        _slot(start, 25.0),
        _slot(start + timedelta(minutes=30), 9.0),
        _slot(start + timedelta(hours=1), 22.0),
    ]
    segments = [
        *_half_hour_segments(start, solar_kw=0.0, battery_kw=7.0),
        *_half_hour_segments(
            start + timedelta(minutes=30), solar_kw=4.0, battery_kw=3.0
        ),
        *_half_hour_segments(start + timedelta(hours=1), solar_kw=0.0, battery_kw=7.0),
    ]

    plan = allocate_forecast_path_exports(
        slots=slots,
        capacity_segments=segments,
        now=start,
        deadline=start + timedelta(hours=1, minutes=30),
        battery_capacity_kwh=10.0,
        soc_percent=25.0,
        target_soc_percent=20.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        max_charge_kw=7.0,
        house_kw=0.0,
        export_limit_kw=7.0,
        minimum_export_rate_pence=3.5,
    )

    early = plan.allocations[0]
    assert early.rate_pence == 25.0
    assert 0.49 <= early.planned_battery_export_kwh <= 0.501
    assert plan.minimum_soc_percent >= 20.0 - 1e-5


def test_runtime_installs_after_total_ledger_and_keeps_writes_blocked() -> None:
    compat = (ROOT / "custom_components/kems/agile_alpha7_compat.py").read_text()
    runtime = (
        ROOT / "custom_components/kems/agile_forecast_path_scheduler.py"
    ).read_text()
    pure = (
        ROOT / "custom_components/kems/kems_core/forecast_path_scheduler.py"
    ).read_text()

    assert compat.index("install_forecast_path_scheduler") > compat.index(
        "install_total_discharge_ledger"
    )
    assert "deadline_runtime._capacity_segments" in runtime
    assert "MIN_FORECAST_CONFIDENCE_PERCENT = 70.0" in runtime
    assert '"future_solar_borrowing": False' in runtime
    assert '"hardware_writes": "blocked"' in runtime
    assert "_BINARY_SEARCH_STEPS" in pure
    assert "battery + 1e-7 < target_stored" in pure


def test_alpha913_version_and_release_scope() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())

    assert manifest["version"] == "0.9.0-alpha9.28"
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert "forecast-aware" in bundle["maintenance"]["reason"].lower()
    assert "hardware writes" in bundle["maintenance"]["reason"].lower()
