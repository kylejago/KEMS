"""Regression tests for read-only private Octopus CSV supplier comparisons."""

from __future__ import annotations

import copy
import csv
import io
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from kems_core.supplier_meter_reconciliation import (
    _expected_slots,
    parse_octopus_csv,
    reconcile_supplier_history,
)

LONDON = ZoneInfo("Europe/London")


def _csv(
    day: date,
    *,
    kwh: float = 1.0,
    omit: set[int] | None = None,
    repeat: set[int] | None = None,
    extra_cheap: set[int] | None = None,
    special: dict[int, float] | None = None,
) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Consumption (kwh)",
            " Estimated Cost Inc. Tax (p) if applicable",
            " Standing Charge Inc. Tax (p) if applicable",
            " Start",
            " End",
        ]
    )
    starts = sorted(_expected_slots(day))
    for index, start in enumerate(starts):
        if index in (omit or set()):
            continue
        end = start + timedelta(minutes=30)
        energy = (special or {}).get(index, kwh)
        local = start.astimezone(LONDON).time()
        cheap = local >= time(23, 30) or local < time(5, 30)
        rate = 6.6 if cheap or index in (extra_cheap or set()) else 35.8
        row = [energy, round(energy * rate, 5), 1.15, start.isoformat(), end.isoformat()]
        writer.writerow(row)
        if index in (repeat or set()):
            writer.writerow(row)
    return output.getvalue()


def _compare(
    import_source: str | None,
    export_source: str | None,
    *,
    date_text: str = "2026-11-17",
    actual_import: float = 48.0,
    actual_export: float = 48.0,
) -> dict:
    previous = {
        date_text: {
            "grid_import_kwh": actual_import,
            "grid_export_kwh": actual_export,
        }
    }
    unchanged = copy.deepcopy(previous)
    result = reconcile_supplier_history(
        imported=(
            parse_octopus_csv(import_source, direction="import")
            if import_source is not None
            else None
        ),
        exported=(
            parse_octopus_csv(export_source, direction="export")
            if export_source is not None
            else None
        ),
        kems_days=previous,
        coverage_days=[
            {
                "date": date_text,
                "recorded_totals_available": True,
                "simulation_replay_complete": False,
                "simulation_data_coverage_percent": 95.3,
            }
        ],
        now=datetime(2026, 11, 18, 22, 30, tzinfo=UTC),
    )
    assert previous == unchanged
    assert result["no_roi_refund_or_income_adjustment"] is True
    assert result["no_tariff_or_battery_or_export_control_authority"] is True
    assert result["no_historical_day_promotion_or_backfill"] is True
    return result


def test_complete_48_slot_days_can_corroborate_while_simulation_stays_partial() -> None:
    source = _csv(date(2026, 11, 17))
    report = _compare(source, source)
    day = report["days"][0]
    assert day["supplier_import"]["expected_half_hour_slots"] == 48
    assert day["supplier_export"]["present_half_hour_slots"] == 48
    assert day["supplier_import"]["half_hour_coverage_complete"] is True
    assert day["grid_import_comparison"]["status"] == "within_investigation_tolerance"
    assert day["grid_export_comparison"]["supplier_minus_kems_kwh"] == 0
    assert day["simulation_replay_complete_unchanged"] is False
    assert day["recorded_actuals_present"] is True
    assert day["supplier_import"]["standing_charge_included"] is False
    assert report["supplier_costs_are_estimated"] is True


def test_supplier_kwh_difference_is_reported_not_written() -> None:
    source = _csv(date(2026, 11, 17))
    report = _compare(source, source, actual_import=45.0)
    cmp = report["days"][0]["grid_import_comparison"]
    assert cmp["supplier_minus_kems_kwh"] == 3.0
    assert cmp["status"] == "supplier_kems_difference_requires_investigation"
    assert cmp["tolerance_is_not_billing_or_meter_certification"] is True


def test_missing_interval_prevents_supplier_complete_claim() -> None:
    source = _csv(date(2026, 11, 17), omit={7})
    report = _compare(source, source)
    day = report["days"][0]
    assert day["supplier_import"]["present_half_hour_slots"] == 47
    assert day["supplier_import"]["missing_half_hour_slots"] == 1
    assert day["grid_import_comparison"]["status"] == "supplier_coverage_incomplete"
    assert not day["grid_import_comparison"]["supplier_corroboration_within_two_percent"]


def test_duplicate_input_cannot_double_count_or_certify() -> None:
    source = _csv(date(2026, 11, 17), repeat={3})
    parsed = parse_octopus_csv(source, direction="import")
    assert len(parsed["rows"]) == 48
    assert len(parsed["duplicate_intervals"]) == 1
    report = _compare(source, source)
    assert report["status"] == "csv_source_has_invalid_or_duplicate_rows"
    assert report["days"][0]["csv_source_integrity_warning"] is True
    assert report["days"][0]["supplier_import"]["half_hour_coverage_complete"] is False


def test_uk_dst_expected_slot_count_46_or_50() -> None:
    assert len(_expected_slots(date(2026, 3, 29))) == 46
    assert len(_expected_slots(date(2026, 10, 25))) == 50
    for day in (date(2026, 3, 29), date(2026, 10, 25)):
        source = parse_octopus_csv(_csv(day), direction="import")
        starts = {row["start"] for row in source["rows"]}
        assert len(starts) == len(_expected_slots(day))


def test_extra_cheap_slot_identification_is_historical_only() -> None:
    day = date(2026, 11, 17)
    starts = sorted(_expected_slots(day))
    index_0630 = next(
        i for i, start in enumerate(starts)
        if start.astimezone(LONDON).time() == time(6, 30)
    )
    index_0700 = index_0630 + 1
    source = _csv(
        day,
        extra_cheap={index_0630, index_0700},
        special={index_0630: 4.5, index_0700: 0.05},
    )
    report = _compare(source, source, actual_import=51.55, actual_export=51.55)
    daily = report["days"][0]
    assert daily["extra_cheap_slot_count"] == 2
    assert {x["start"][-14:-6] for x in daily["extra_cheap_import_candidate_slots"]} == {
        "06:30:00",
        "07:00:00",
    }
    assert all(
        item["proves_future_dispatch_or_tariff"] is False
        for item in daily["extra_cheap_import_candidate_slots"]
    )


def test_missing_csv_is_explicit_not_silently_complete() -> None:
    report = _compare(None, None)
    assert report["status"] == "awaiting_local_octopus_csv"
    assert report["days"] == []


def test_naive_bad_and_negative_csv_rows_rejected() -> None:
    data = _csv(date(2026, 11, 17))
    data += "-1,0,0,2026-11-18T03:00:00+00:00,2026-11-18T03:30:00+00:00\n"
    data += "1,0,0,2026-11-18T04:00:00,2026-11-18T04:30:00\n"
    data += "1,0,0,2026-11-18T05:00:00+00:00,2026-11-18T05:31:00+00:00\n"
    parsed = parse_octopus_csv(data, direction="import")
    assert parsed["invalid_rows"] == 3
    assert len(parsed["rows"]) == 48


def test_missing_estimated_price_is_never_assumed_zero() -> None:
    data = _csv(date(2026, 11, 17))
    data = data.replace(",35.8,1.15", ",no data,1.15", 1)
    parsed = parse_octopus_csv(data, direction="import")
    assert parsed["rows"][0]["estimated_cost_pence"] is None
    report = _compare(data, data)
    assert report["days"][0]["supplier_import"]["estimated_energy_cost_pence"] is None
    assert report["days"][0]["supplier_import"]["half_hour_coverage_complete"] is True
