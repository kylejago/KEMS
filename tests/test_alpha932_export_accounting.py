"""Regression proof for Alpha9.32 actual export accounting."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

from custom_components.kems.export_accounting import (
    actual_export_income_pence,
    async_repair_no_paid_export_income,
    current_export_rate_pence,
    revalue_actual_export_income,
)
from custom_components.kems.kems_core import SimulationState, Snapshot


def _records(*exports_kw: float) -> list[Snapshot]:
    start = datetime(2026, 9, 13, 11, 0, tzinfo=UTC)
    return [
        Snapshot(
            timestamp=start + timedelta(minutes=30 * index),
            grid_export_kw=export_kw,
        )
        for index, export_kw in enumerate(exports_kw)
    ]


def _agile_state() -> dict:
    return {
        "current_rate_pence": 20.0,
        "today_slots": [
            {
                "valid_from": "2026-09-13T11:00:00+00:00",
                "valid_to": "2026-09-13T11:30:00+00:00",
                "rate_pence": 5.0,
            },
            {
                "valid_from": "2026-09-13T11:30:00+00:00",
                "valid_to": "2026-09-13T12:00:00+00:00",
                "rate_pence": 20.0,
            },
        ],
    }


def test_no_paid_export_values_measured_export_at_zero() -> None:
    records = _records(2.0, 4.0, 0.0)
    income = actual_export_income_pence(
        records,
        records[-1].timestamp,
        tariff_type="none",
        fixed_rate_pence=12.0,
        agile_state=_agile_state(),
    )

    assert income == 0.0
    assert records[0].grid_export_kw == 2.0
    assert (
        current_export_rate_pence(
            tariff_type="none",
            fixed_rate_pence=12.0,
            agile_state=_agile_state(),
        )
        == 0.0
    )


def test_fixed_export_uses_configured_fixed_rate() -> None:
    records = _records(2.0, 4.0, 0.0)
    income = actual_export_income_pence(
        records,
        records[-1].timestamp,
        tariff_type="fixed",
        fixed_rate_pence=15.0,
        agile_state=_agile_state(),
    )

    # 1 kWh + 2 kWh at 15p/kWh.
    assert income == 45.0
    assert (
        current_export_rate_pence(
            tariff_type="fixed",
            fixed_rate_pence=15.0,
            agile_state=_agile_state(),
        )
        == 15.0
    )


def test_agile_export_uses_each_half_hour_price() -> None:
    records = _records(2.0, 4.0, 0.0)
    income = actual_export_income_pence(
        records,
        records[-1].timestamp,
        tariff_type="agile",
        fixed_rate_pence=12.0,
        agile_state=_agile_state(),
    )

    # 1 kWh at 5p plus 2 kWh at 20p. The 12p benchmark is not used.
    assert income == 45.0
    assert (
        current_export_rate_pence(
            tariff_type="agile",
            fixed_rate_pence=12.0,
            agile_state=_agile_state(),
        )
        == 20.0
    )


def test_agile_negative_price_is_preserved() -> None:
    records = _records(2.0, 0.0)
    state = _agile_state()
    state["current_rate_pence"] = -3.0
    state["today_slots"] = [
        {
            "valid_from": "2026-09-13T11:00:00+00:00",
            "valid_to": "2026-09-13T11:30:00+00:00",
            "rate_pence": -3.0,
        }
    ]

    income = actual_export_income_pence(
        records,
        records[-1].timestamp,
        tariff_type="agile",
        fixed_rate_pence=12.0,
        agile_state=state,
    )

    assert income == -3.0
    assert (
        current_export_rate_pence(
            tariff_type="agile",
            fixed_rate_pence=12.0,
            agile_state=state,
        )
        == -3.0
    )


def test_agile_positive_export_without_price_fails_closed() -> None:
    records = _records(2.0, 4.0, 0.0)
    incomplete = _agile_state()
    incomplete["today_slots"] = incomplete["today_slots"][:1]

    assert (
        actual_export_income_pence(
            records,
            records[-1].timestamp,
            tariff_type="agile",
            fixed_rate_pence=12.0,
            agile_state=incomplete,
        )
        is None
    )


def test_revalue_updates_all_actual_financial_fields() -> None:
    state = SimulationState(
        actual_cost_pence=100.0,
        actual_import_cost_pence=100.0,
        actual_export_income_pence=36.0,
        actual_avoided_import_value_pence=25.0,
        actual_system_value_pence=61.0,
        simulated_cost_pence=50.0,
        saving_pence=50.0,
    )

    result = revalue_actual_export_income(state, 45.0)

    assert result.actual_export_income_pence == 45.0
    assert result.actual_cost_pence == 55.0
    assert result.actual_system_value_pence == 70.0
    assert result.saving_pence == 5.0


class _FakeLedger:
    commissioning_date = None
    actual_system_value_pence = 0.0


class _FakeRecorder:
    def __init__(self) -> None:
        self._daily_records = {
            "2026-09-11": {
                "grid_export_kwh": 1.0,
                "export_income_pence": 12.0,
            },
            "2026-09-12": {
                "grid_export_kwh": 8.2,
                "export_income_pence": 98.4,
                "actual_avoided_import_value_pence": 40.0,
                "actual_system_value_pence": 138.4,
            },
        }
        self._tracking_date = date(2026, 9, 13)
        self._tracking_values = {
            "grid_export_kwh": 14.2,
            "export_income_pence": 170.4,
            "actual_avoided_import_value_pence": 188.6,
            "actual_system_value_pence": 359.0,
        }
        self._ledger = _FakeLedger()
        self.saved = False
        self.reconciled = False

    def _reconcile_observed_totals(self) -> None:
        self.reconciled = True

    async def async_save(self) -> None:
        self.saved = True


def test_no_paid_export_repair_zeroes_latest_two_days_only() -> None:
    recorder = _FakeRecorder()

    changed = asyncio.run(async_repair_no_paid_export_income(recorder))

    assert changed is True
    assert recorder._daily_records["2026-09-11"]["export_income_pence"] == 12.0
    assert recorder._daily_records["2026-09-12"]["grid_export_kwh"] == 8.2
    assert recorder._daily_records["2026-09-12"]["export_income_pence"] == 0.0
    assert recorder._daily_records["2026-09-12"]["actual_system_value_pence"] == 40.0
    assert recorder._tracking_values["grid_export_kwh"] == 14.2
    assert recorder._tracking_values["export_income_pence"] == 0.0
    assert recorder._tracking_values["actual_system_value_pence"] == 188.6
    assert recorder.reconciled is True
    assert recorder.saved is True

    # Migration is idempotent on subsequent startup/reload.
    recorder.saved = False
    assert asyncio.run(async_repair_no_paid_export_income(recorder)) is False
    assert recorder.saved is False
