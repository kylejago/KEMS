"""Read-only Octopus CSV vs KEMS actual-energy evidence.

CSV data is optional, private, imported locally by the owner. It must never
authorize live cheap charging, overwrite an energy ledger, mark replay complete,
or treat estimated Octopus CSV costs as settled bills.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from math import isfinite
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
MAX_CSV_ROWS = 3500
MAX_REPORT_DAYS = 32
HALF_HOUR = timedelta(minutes=30)
ENERGY_TOLERANCE_PERCENT = 2.0
MIN_CHEAP_COMPARISON_KWH = Decimal("0.02")
RATE_MATCH_PENCE = 0.15


def _decimal(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(UTC) if stamp.tzinfo is not None else None


def parse_octopus_csv(text: str, *, direction: str) -> dict[str, Any]:
    """Parse a bounded Octopus export; reject duplicate or invalid half-hours.

    Never accept a guessed unit or a timezone-naive time. Missing estimated
    prices remain missing; do not infer payment from physical energy.
    """
    if direction not in {"import", "export"}:
        raise ValueError("Expected import or export direction")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("Missing Octopus CSV header")
    headers = {field.strip().lower(): field for field in reader.fieldnames}
    columns = {
        "energy": headers.get("consumption (kwh)"),
        "start": headers.get("start"),
        "end": headers.get("end"),
        "estimated": next(
            (field for label, field in headers.items() if label.startswith("estimated cost inc. tax (p)")),
            None,
        ),
    }
    if not all(columns.values()):
        raise ValueError("CSV is missing Octopus consumption, cost, start or end columns")
    intervals: dict[datetime, dict[str, Any]] = {}
    duplicate_intervals: set[str] = set()
    invalid_rows = 0
    total_rows = 0
    for row in reader:
        total_rows += 1
        if total_rows > MAX_CSV_ROWS:
            raise ValueError("Octopus CSV exceeds bounded input rows")
        start = _timestamp(row.get(columns["start"]))
        end = _timestamp(row.get(columns["end"]))
        kwh = _decimal(row.get(columns["energy"]))
        cost = _decimal(row.get(columns["estimated"]))
        if (
            start is None
            or end is None
            or end - start != HALF_HOUR
            or kwh is None
            or not isinstance(row, dict)
        ):
            invalid_rows += 1
            continue
        if start in intervals:
            duplicate_intervals.add(start.isoformat())
            continue
        intervals[start] = {
            "start": start,
            "end": end,
            "kwh": kwh,
            "estimated_cost_pence": cost,
            "local_day": start.astimezone(LONDON).date().isoformat(),
        }
    return {
        "direction": direction,
        "rows": sorted(intervals.values(), key=lambda r: r["start"]),
        "total_rows": total_rows,
        "invalid_rows": invalid_rows,
        "duplicate_intervals": sorted(duplicate_intervals),
        "estimated_cost_is_not_settlement": True,
    }


def _expected_slots(day: date) -> set[datetime]:
    start = datetime.combine(day, time.min, tzinfo=LONDON).astimezone(UTC)
    finish = datetime.combine(
        day + timedelta(days=1), time.min, tzinfo=LONDON
    ).astimezone(UTC)
    return {
        start + HALF_HOUR * index
        for index in range(int((finish - start) / HALF_HOUR))
    }


def _regular_cheap_time(local_time: time) -> bool:
    return local_time >= time(23, 30) or local_time < time(5, 30)


def _rates(rows: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    cheap: list[float] = []
    day: list[float] = []
    for row in rows:
        energy = row["kwh"]
        estimated = row["estimated_cost_pence"]
        if estimated is None or energy < MIN_CHEAP_COMPARISON_KWH:
            continue
        price = float(estimated / energy)
        if not isfinite(price):
            continue
        local_time = row["start"].astimezone(LONDON).time()
        if _regular_cheap_time(local_time):
            cheap.append(price)
        elif time(8) <= local_time < time(17):
            day.append(price)
    return (median(cheap) if cheap else None, median(day) if day else None)


def _slot_summary(rows: list[dict[str, Any]], day_text: str) -> dict[str, Any]:
    day = date.fromisoformat(day_text)
    expected = _expected_slots(day)
    slots = {row["start"] for row in rows}
    valid = slots == expected
    estimated_rows = [row for row in rows if row["estimated_cost_pence"] is not None]
    return {
        "date": day_text,
        "expected_half_hour_slots": len(expected),
        "present_half_hour_slots": len(slots & expected),
        "missing_half_hour_slots": len(expected - slots),
        "unexpected_half_hour_slots": len(slots - expected),
        "half_hour_coverage_complete": valid,
        "energy_kwh": round(float(sum((r["kwh"] for r in rows), Decimal(0))), 3),
        "estimated_energy_cost_pence": (
            round(
                float(
                    sum(
                        (r["estimated_cost_pence"] for r in estimated_rows),
                        Decimal(0),
                    )
                ),
                2,
            )
            if len(estimated_rows) == len(rows)
            else None
        ),
        "standing_charge_included": False,
        "estimated_cost_is_not_settlement": True,
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return None
    return candidate if isfinite(candidate) and candidate >= 0 else None


def _compare(supplier: dict[str, Any] | None, ledger_kwh: Any) -> dict[str, Any]:
    actual = _number(ledger_kwh)
    if not supplier or not supplier["half_hour_coverage_complete"]:
        return {
            "status": "supplier_coverage_incomplete",
            "kems_actual_kwh": actual,
            "supplier_minus_kems_kwh": None,
            "supplier_corroboration_within_two_percent": False,
        }
    if actual is None:
        return {
            "status": "kems_recorded_actual_unavailable",
            "kems_actual_kwh": None,
            "supplier_minus_kems_kwh": None,
            "supplier_corroboration_within_two_percent": False,
        }
    supplier_kwh = supplier["energy_kwh"]
    diff = supplier_kwh - actual
    percentage = abs(diff) / max(supplier_kwh, actual, 0.001) * 100
    return {
        "status": (
            "within_investigation_tolerance"
            if percentage <= ENERGY_TOLERANCE_PERCENT
            else "supplier_kems_difference_requires_investigation"
        ),
        "kems_actual_kwh": round(actual, 3),
        "supplier_minus_kems_kwh": round(diff, 3),
        "absolute_difference_percent": round(percentage, 3),
        "supplier_corroboration_within_two_percent": (
            percentage <= ENERGY_TOLERANCE_PERCENT
        ),
        "tolerance_is_not_billing_or_meter_certification": True,
    }


def _cost_evidence(
    supplier: dict[str, Any] | None,
    kems_pence: Any,
    *,
    direction: str,
) -> dict[str, Any]:
    """Expose non-equivalent pricing figures without suggesting settlement."""
    previous = _number(kems_pence)
    estimated = (
        supplier.get("estimated_energy_cost_pence") if supplier else None
    )
    return {
        "direction": direction,
        "kems_calculated_pence": previous,
        "octopus_estimated_energy_pence": estimated,
        "supplier_estimated_minus_kems_pence": (
            round(estimated - previous, 2)
            if estimated is not None and previous is not None
            else None
        ),
        "no_standing_charges_in_supplier_comparison": True,
        "kems_and_supplier_tariff_pricing_may_differ": True,
        "not_settled_supplier_payout_or_authoritative_roi": True,
    }


def _export_interval_examples(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bounded supplier half-hours for comparing independent export with twin."""
    active = sorted(
        (item for item in rows if item["kwh"] > 0),
        key=lambda item: item["kwh"],
        reverse=True,
    )
    return [
        {
            "start": item["start"].isoformat(),
            "end": item["end"].isoformat(),
            "supplier_export_kwh": round(float(item["kwh"]), 3),
            "supplier_estimated_income_pence": (
                round(float(item["estimated_cost_pence"]), 2)
                if item["estimated_cost_pence"] is not None
                else None
            ),
            "matched_kems_half_hour_physical_sample": False,
            "model_vs_meter_comparison_required": True,
        }
        for item in active[:12]
    ]


def _extra_cheap_slots(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cheap, regular = _rates(rows)
    if cheap is None or regular is None or regular <= cheap * 1.3:
        return []
    candidates = []
    for row in rows:
        local = row["start"].astimezone(LONDON)
        if _regular_cheap_time(local.time()):
            continue
        energy = row["kwh"]
        cost = row["estimated_cost_pence"]
        if energy < MIN_CHEAP_COMPARISON_KWH or cost is None:
            continue
        price = float(cost / energy)
        if price > 0.5 and abs(price - cheap) <= RATE_MATCH_PENCE:
            candidates.append(
                {
                    "start": row["start"].isoformat(),
                    "end": row["end"].isoformat(),
                    "kwh": round(float(energy), 3),
                    "supplier_estimated_rate_pence_per_kwh": round(price, 4),
                    "estimated_difference_to_typical_day_rate_pence": round(
                        float(energy) * (regular - price), 2
                    ),
                    "historical_discount_candidate_only": True,
                    "proves_future_dispatch_or_tariff": False,
                }
            )
    return candidates


def reconcile_supplier_history(
    *,
    imported: Mapping[str, Any] | None,
    exported: Mapping[str, Any] | None,
    kems_days: Mapping[str, Mapping[str, Any]],
    coverage_days: list[Mapping[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Supplier coverage and actuals, separate from simulation replay status."""
    coverage = {
        str(row.get("date")): row
        for row in coverage_days
        if isinstance(row, Mapping) and row.get("date")
    }
    groups: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"import": [], "export": []}
    )
    for direction, source in (("import", imported), ("export", exported)):
        if source is None:
            continue
        for row in source["rows"]:
            groups[row["local_day"]][direction].append(row)
    today = now.astimezone(LONDON).date()
    lower = today - timedelta(days=MAX_REPORT_DAYS - 1)
    days = []
    for day_text, daily in sorted(groups.items()):
        day = date.fromisoformat(day_text)
        if not lower <= day <= today:
            continue
        import_summary = (
            _slot_summary(daily["import"], day_text) if imported else None
        )
        export_summary = (
            _slot_summary(daily["export"], day_text) if exported else None
        )
        led = kems_days.get(day_text) or {}
        replay = coverage.get(day_text) or {}
        candidate_slots = _extra_cheap_slots(daily["import"])
        days.append(
            {
                "date": day_text,
                "ongoing_day": day == today,
                "recorded_actuals_present": bool(
                    replay.get("recorded_totals_available")
                ),
                "simulation_replay_complete_unchanged": (
                    replay.get("simulation_replay_complete")
                ),
                "simulation_data_coverage_percent": replay.get(
                    "simulation_data_coverage_percent"
                ),
                "supplier_import": import_summary,
                "supplier_export": export_summary,
                "grid_import_comparison": _compare(
                    import_summary, led.get("grid_import_kwh")
                ),
                "grid_export_comparison": _compare(
                    export_summary, led.get("grid_export_kwh")
                ),
                "import_energy_cost_evidence": _cost_evidence(
                    import_summary, led.get("import_cost_pence"), direction="import"
                ),
                "export_energy_income_evidence": _cost_evidence(
                    export_summary, led.get("export_income_pence"), direction="export"
                ),
                "supplier_export_half_hour_examples": _export_interval_examples(
                    daily["export"]
                ),
                "extra_cheap_import_candidate_slots": candidate_slots[:12],
                "extra_cheap_slot_count": len(candidate_slots),
                "historical_extra_discount_not_live_dispatch_proof": True,
                "supplier_meter_energy_is_not_simulation_replay": True,
            }
        )
    errors = {}
    for direction, parsed in (("import", imported), ("export", exported)):
        if parsed is not None:
            errors[direction] = {
                "invalid_rows": parsed["invalid_rows"],
                "duplicate_intervals": len(parsed["duplicate_intervals"]),
            }
    suspicious = any(
        value["invalid_rows"] or value["duplicate_intervals"]
        for value in errors.values()
    )
    if suspicious:
        for row in days:
            for direction in ("import", "export"):
                source = row.get(f"supplier_{direction}")
                if source is not None:
                    source["half_hour_coverage_complete"] = False
                    row[f"grid_{direction}_comparison"] = _compare(
                        source,
                        (kems_days.get(row["date"]) or {}).get(
                            f"grid_{direction}_kwh"
                        ),
                    )
            row["csv_source_integrity_warning"] = True
    return {
        "status": (
            "awaiting_local_octopus_csv"
            if imported is None and exported is None
            else "csv_source_has_invalid_or_duplicate_rows"
            if suspicious
            else "read_only_supplier_comparison"
        ),
        "import_csv_present": imported is not None,
        "export_csv_present": exported is not None,
        "source_validation": errors,
        "days": days[-MAX_REPORT_DAYS:],
        "supplier_costs_are_estimated": True,
        "supplier_interval_completeness_is_not_simulation_completeness": True,
        "kems_recorded_totals_are_not_rewritten": True,
        "no_tariff_or_battery_or_export_control_authority": True,
        "no_roi_refund_or_income_adjustment": True,
        "no_historical_day_promotion_or_backfill": True,
        "next_step": (
            "Review any supplier-vs-KEMS meter deltas and account for CT "
            "measurement scope, 0.1kWh register precision and settlement "
            "timing. Historical cheap-slot prices never prove live discount."
        ),
    }
