"""Supplier-estimated electricity charges, separate from live control and ROI."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from typing import Any

from .supplier_intervals import _HALF_HOUR, _LONDON, _utc, normalise_interval

CHARGE_FORMAT = "kems-supplier-charges-v1"
ELECTRICITY = ("electricity_import", "electricity_export")


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if isfinite(value) else None


class SupplierChargeEvidence:
    """First-seen estimates with independent energy matching and conflict checks."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.conflicts: set[tuple[str, str, str]] = set()

    def ingest(self, rows: Iterable[Any], *, source: str, now: datetime) -> bool:
        changed = False
        for raw in rows:
            if not isinstance(raw, Mapping) or raw.get("kind") not in ELECTRICITY:
                continue
            interval = normalise_interval(raw, source=source, now=now)
            charge = _finite(raw.get("charge_pence"))
            if interval is None or charge is None:
                continue
            if interval["kwh"] == 0 and abs(charge) > 0.01:
                continue
            key = (interval["kind"], interval["start"], source)
            row = {**interval, "charge_pence": charge}
            prior = self.rows.get(key)
            if prior is None:
                self.rows[key] = row
                changed = True
            elif (
                abs(prior["kwh"] - row["kwh"]) > 0.000001
                or abs(prior["charge_pence"] - charge) > 0.000001
            ) and key not in self.conflicts:
                self.conflicts.add(key)
                changed = True
        return changed

    def dump(self) -> dict[str, Any]:
        return {
            "format": CHARGE_FORMAT,
            "rows": list(self.rows.values()),
            "conflicts": [list(key) for key in sorted(self.conflicts)],
        }

    def restore(self, stored: Any, *, now: datetime) -> None:
        if not isinstance(stored, dict) or stored.get("format") != CHARGE_FORMAT:
            return
        for row in stored.get("rows") or []:
            if isinstance(row, dict) and row.get("source") in (
                "octopus_csv",
                "octopus_integration",
            ):
                self.ingest([row], source=row["source"], now=now)
        for key in stored.get("conflicts") or []:
            if (
                isinstance(key, list)
                and len(key) == 3
                and all(isinstance(x, str) for x in key)
                and tuple(key) in self.rows
            ):
                self.conflicts.add(tuple(key))

    def reconciliation(
        self, energy, daily_records: Mapping[str, Any], *, now: datetime,
        commissioning_date: Any,
    ) -> dict[str, Any]:
        """Compare complete, matching priced days; no estimate becomes settlement."""
        try:
            commissioned = date.fromisoformat(str(commissioning_date))
        except (TypeError, ValueError):
            commissioned = None
        today = now.astimezone(_LONDON).date()
        grouped: dict[tuple[str, date], list[float]] = defaultdict(list)
        invalid = 0
        overlapping = defaultdict(list)
        for key, row in self.rows.items():
            overlapping[key[:2]].append((key, row))
        for key, candidates in overlapping.items():
            physical = energy.rows.get(key)
            if physical is None or key in energy.conflicts:
                invalid += 1
                continue
            if any(
                k in self.conflicts
                or abs(row["kwh"] - physical["kwh"]) > 0.000001
                or row["end"] != physical["end"]
                for k, row in candidates
            ):
                invalid += 1
                continue
            values = [row["charge_pence"] for _, row in candidates]
            # Supplier CSV may round to 0.01p. Do not mask material disagreements.
            if max(values) - min(values) > 0.011:
                invalid += 1
                continue
            selected = next(
                (row for _, row in candidates if row["source"] == "octopus_csv"),
                candidates[0][1],
            )
            day = datetime.fromisoformat(key[1]).astimezone(_LONDON).date()
            grouped[(key[0], day)].append(selected["charge_pence"])
        result = {}
        for kind, field in (
            ("electricity_import", "import_cost_pence"),
            ("electricity_export", "export_income_pence"),
        ):
            comparisons = []
            before_commissioning = 0
            for (group_kind, day), charges in sorted(grouped.items()):
                if group_kind != kind or day >= today:
                    continue
                start = datetime.combine(day, datetime.min.time(), _LONDON)
                end = datetime.combine(
                    day + timedelta(days=1), datetime.min.time(), _LONDON
                )
                expected = int((end.astimezone(UTC) - start.astimezone(UTC)) / _HALF_HOUR)
                if len(charges) != expected:
                    continue
                if commissioned is None or day <= commissioned:
                    before_commissioning += 1
                    continue
                value = round(sum(charges), 6)
                stored = daily_records.get(day.isoformat())
                recorded = _finite(stored.get(field)) if isinstance(stored, Mapping) else None
                comparisons.append(
                    {
                        "date": day.isoformat(),
                        "supplier_estimate_pence": value,
                        "recorded_pence": recorded,
                        "supplier_minus_recorded_pence": (
                            round(value - recorded, 6) if recorded is not None else None
                        ),
                    }
                )
            matched = [
                row for row in comparisons
                if row["supplier_minus_recorded_pence"] is not None
            ]
            result[kind] = {
                "complete_priced_post_commissioning_days": len(comparisons),
                "excluded_before_or_unknown_commissioning_days": before_commissioning,
                "comparable_days": len(matched),
                "supplier_estimate_on_comparable_days_pence": (
                    round(sum(row["supplier_estimate_pence"] for row in matched), 6)
                    if matched else None
                ),
                "recorded_on_comparable_days_pence": (
                    round(sum(row["recorded_pence"] for row in matched), 6)
                    if matched else None
                ),
                "difference_pence": (
                    round(sum(row["supplier_minus_recorded_pence"] for row in matched), 6)
                    if matched else None
                ),
                "recent_days": comparisons[-14:],
            }
        return {
            "scope": "supplier_estimated_gross_energy_charge_comparison",
            "retained_charge_observations": len(self.rows),
            "unmatched_or_conflicted_intervals": invalid,
            "financial_commissioning_date": commissioned.isoformat() if commissioned else None,
            "kinds": result,
            "standing_charges_and_event_rewards_excluded": True,
            "supplier_settlement_verified": False,
            "roi_or_ledger_write_authorised": False,
        }


def exact_event_meter_totals(energy, start: datetime, end: datetime) -> dict[str, Any] | None:
    """No partial half-hours, missing meter readings, or implicit zero export."""
    if (
        start.tzinfo is None or end.tzinfo is None or end <= start
        or end - start > timedelta(hours=24)
    ):
        return None
    cursor = start.astimezone(UTC)
    end = end.astimezone(UTC)
    totals = dict.fromkeys(ELECTRICITY, 0.0)
    while cursor < end:
        following = cursor + _HALF_HOUR
        if following > end:
            return None
        for kind in ELECTRICITY:
            key = (kind, cursor.isoformat())
            row = energy.rows.get(key)
            if (
                row is None or key in energy.conflicts
                or _utc(row["end"]) != following
            ):
                return None
            totals[kind] += row["kwh"]
        cursor = following
    return totals


def exact_completed_baseline(attributes: Any, start: datetime, end: datetime) -> float | None:
    """Require complete, contiguous supplier baseline rows for this exact event."""
    if not isinstance(attributes, Mapping):
        return None
    rows = attributes.get("baselines")
    if not isinstance(rows, list) or not rows:
        return None
    verified = []
    for row in rows:
        if not isinstance(row, Mapping):
            return None
        left, right = _utc(row.get("start")), _utc(row.get("end"))
        value = _finite(row.get("baseline"))
        if (
            left is None or right is None or not start <= left < right <= end
            or value is None or value < 0
            or row.get("is_incomplete_calculation") is not False
        ):
            return None
        verified.append((left, right, value))
    cursor = start
    total = 0.0
    for left, right, value in sorted(verified):
        if left != cursor:
            return None
        cursor = right
        total += value
    reported = _finite(attributes.get("total_baseline"))
    if cursor != end or (reported is not None and abs(reported - total) > 0.001):
        return None
    return total


def capture_completed_baseline(
    event: Mapping[str, Any], import_attrs: Any, export_attrs: Any,
    *, now: datetime, points_per_kwh: Any = None,
) -> dict[str, Any] | None:
    """Retain both exact baseline windows even before meter readings arrive."""
    start, end = _utc(event.get("session_start")), _utc(event.get("session_end"))
    event_id = event.get("session_id")
    if (
        event.get("available") is not True or not event_id
        or start is None or end is None or not start < end <= now
    ):
        return None
    imported = exact_completed_baseline(import_attrs, start, end)
    exported = exact_completed_baseline(export_attrs, start, end)
    if imported is None or exported is None:
        return None
    rate = _finite(points_per_kwh)
    return {
        "session_id": str(event_id),
        "session_start": start.isoformat(),
        "session_end": end.isoformat(),
        "import_baseline_kwh": imported,
        "export_baseline_kwh": exported,
        "octopoints_per_kwh": rate if rate is not None and rate >= 0 else None,
    }


def completed_power_down_estimate(energy, baseline: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate retained exact baseline against current non-conflicting meter evidence."""
    result = {
        **baseline,
        "supplier_settled": False,
        "roi_or_ledger_write_authorised": False,
        "estimated_bonus_pence": None,
        "estimated_rewardable_reduction_kwh": None,
        "status": "awaiting_complete_supplier_meter_intervals",
    }
    if baseline.get("conflict"):
        result["status"] = "conflicting_baseline_evidence"
        return result
    start, end = _utc(baseline.get("session_start")), _utc(baseline.get("session_end"))
    imported = _finite(baseline.get("import_baseline_kwh"))
    exported = _finite(baseline.get("export_baseline_kwh"))
    if start is None or end is None or imported is None or exported is None:
        result["status"] = "invalid_retained_baseline"
        return result
    actual = exact_event_meter_totals(energy, start, end)
    if actual is None:
        return result
    reduction = max(
        imported - exported - actual["electricity_import"] + actual["electricity_export"],
        0.0,
    )
    rate = _finite(baseline.get("octopoints_per_kwh"))
    result.update({
        "supplier_import_kwh": actual["electricity_import"],
        "supplier_export_kwh": actual["electricity_export"],
        "estimated_rewardable_reduction_kwh": round(reduction, 6),
        "estimated_bonus_pence": (
            round(reduction * rate / 8, 6) if rate is not None and rate >= 0 else None
        ),
        "status": (
            "unsettled_event_estimate"
            if rate is not None and rate >= 0 else "matched_energy_rate_unavailable"
        ),
    })
    return result
