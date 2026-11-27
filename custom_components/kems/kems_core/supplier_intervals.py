"""Idempotent, separate supplier interval evidence; never financial dispatch."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

FORMAT = "kems-supplier-intervals-v1"
KINDS = ("electricity_import", "electricity_export", "gas")
SOURCES = ("octopus_csv", "octopus_integration", "octopus_estimated_gas")
_HALF_HOUR = timedelta(minutes=30)
_LONDON = ZoneInfo("Europe/London")


def _utc(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return stamp.astimezone(UTC) if stamp.tzinfo is not None else None


def normalise_interval(
    row: Mapping[str, Any], *, source: str, now: datetime
) -> dict[str, Any] | None:
    """Accept only complete, finite, explicitly timestamped half-hour rows."""
    kind = row.get("kind")
    start, end = _utc(row.get("start")), _utc(row.get("end"))
    if (
        kind not in KINDS
        or source not in SOURCES
        or now.tzinfo is None
        or start is None
        or end is None
        or start.minute not in (0, 30)
        or start.second
        or start.microsecond
        or end - start != _HALF_HOUR
        or end > now
        or isinstance(row.get("kwh"), bool)
    ):
        return None
    try:
        energy = float(row.get("kwh"))
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(energy) or energy < 0:
        return None
    result = {
        "kind": kind,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "kwh": energy,
        "source": source,
    }
    if kind == "gas" and source != "octopus_csv":
        volume = row.get("consumption_m3")
        if not isinstance(volume, bool):
            try:
                volume = float(volume)
            except (TypeError, ValueError, OverflowError):
                volume = None
            if volume is not None and isfinite(volume) and volume >= 0:
                result["consumption_m3"] = volume
    return result


class SupplierIntervalLedger:
    """Preserve first-seen observations and quarantine conflicting intervals."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.conflicts: set[tuple[str, str]] = set()
        self.quarantined_gas: dict[tuple[str, str], dict[str, Any]] = {}
        self.quarantined_gas_conflicts: set[tuple[str, str]] = set()
        self.gas_daily_reference: dict[str, float] = {}
        self.gas_daily_reference_conflicts: set[str] = set()

    def ingest(self, rows: Iterable[Any], *, source: str, now: datetime) -> bool:
        changed = False
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            row = normalise_interval(raw, source=source, now=now)
            if row is None:
                continue
            key = (row["kind"], row["start"])
            # The installed Octopus previous-day gas feed has produced
            # grossly inflated sums. Preserve raw evidence separately; never
            # let it poison the original CSV or infer a conversion factor.
            unverified_gas = row["kind"] == "gas" and source != "octopus_csv"
            target = self.quarantined_gas if unverified_gas else self.rows
            conflicts = (
                self.quarantined_gas_conflicts if unverified_gas else self.conflicts
            )
            previous = target.get(key)
            if previous is None:
                target[key] = row
                changed = True
            else:
                old_volume = previous.get("consumption_m3")
                new_volume = row.get("consumption_m3")
                if abs(previous["kwh"] - row["kwh"]) > 0.000001 or (
                    old_volume is not None
                    and new_volume is not None
                    and abs(old_volume - new_volume) > 0.000001
                ):
                    if key not in conflicts:
                        conflicts.add(key)
                        changed = True
                elif old_volume is None and new_volume is not None:
                    previous["consumption_m3"] = new_volume
                    changed = True
        return changed

    def ingest_gas_daily_reference(self, rows: Iterable[Any], *, now: datetime) -> bool:
        """Retain corroborated daily HA observations, never synthetic intervals."""
        changed = False
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            try:
                day = date.fromisoformat(str(row.get("date")))
                daily = row.get("daily_kwh")
                lifetime = row.get("lifetime_delta_kwh")
                if isinstance(daily, bool) or isinstance(lifetime, bool):
                    continue
                daily, lifetime = float(daily), float(lifetime)
            except (TypeError, ValueError, OverflowError):
                continue
            if (
                day >= now.astimezone(_LONDON).date()
                or not isfinite(daily)
                or not isfinite(lifetime)
                or min(daily, lifetime) < 0
                or abs(daily - lifetime) > 0.0001
            ):
                continue
            key = day.isoformat()
            prior = self.gas_daily_reference.get(key)
            if prior is None:
                self.gas_daily_reference[key] = daily
                changed = True
            elif (
                abs(prior - daily) > 0.0001
                and key not in self.gas_daily_reference_conflicts
            ):
                self.gas_daily_reference_conflicts.add(key)
                changed = True
        return changed

    def dump(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "rows": list(self.rows.values()),
            "conflicts": [list(key) for key in sorted(self.conflicts)],
            "quarantined_gas_rows": list(self.quarantined_gas.values()),
            "quarantined_gas_conflicts": [
                list(key) for key in sorted(self.quarantined_gas_conflicts)
            ],
            "gas_daily_reference": [
                {"date": day, "daily_kwh": value, "lifetime_delta_kwh": value}
                for day, value in sorted(self.gas_daily_reference.items())
            ],
            "gas_daily_reference_conflicts": sorted(self.gas_daily_reference_conflicts),
        }

    def restore(self, data: Any, *, now: datetime) -> None:
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            return
        for row in data.get("rows") or []:
            if isinstance(row, dict):
                self.ingest([row], source=row.get("source"), now=now)
        for row in data.get("quarantined_gas_rows") or []:
            if (
                isinstance(row, dict)
                and row.get("kind") == "gas"
                and row.get("source") != "octopus_csv"
            ):
                self.ingest([row], source=row.get("source"), now=now)
        self.ingest_gas_daily_reference(data.get("gas_daily_reference") or [], now=now)
        for day in data.get("gas_daily_reference_conflicts") or []:
            if isinstance(day, str) and day in self.gas_daily_reference:
                self.gas_daily_reference_conflicts.add(day)
        for item in data.get("quarantined_gas_conflicts") or []:
            if (
                isinstance(item, list)
                and len(item) == 2
                and all(isinstance(x, str) for x in item)
            ):
                key = tuple(item)
                if key in self.quarantined_gas:
                    self.quarantined_gas_conflicts.add(key)
        for item in data.get("conflicts") or []:
            if (
                isinstance(item, list)
                and len(item) == 2
                and all(isinstance(x, str) for x in item)
            ):
                key = tuple(item)
                if key in self.rows:
                    self.conflicts.add(key)
                elif key in self.quarantined_gas:
                    self.quarantined_gas_conflicts.add(key)

    def complete_day_totals(self, kind: str) -> dict[str, float]:
        """All complete local days; quarantined observations never count."""
        by_day: dict[date, list[float]] = defaultdict(list)
        for key, row in self.rows.items():
            if key[0] == kind and key not in self.conflicts:
                day = datetime.fromisoformat(row["start"]).astimezone(_LONDON).date()
                by_day[day].append(row["kwh"])
        result = {}
        for day, values in sorted(by_day.items()):
            start = datetime.combine(day, datetime.min.time(), _LONDON).astimezone(UTC)
            end = datetime.combine(
                day + timedelta(days=1), datetime.min.time(), _LONDON
            ).astimezone(UTC)
            if len(values) == int((end - start) / _HALF_HOUR):
                result[day.isoformat()] = round(sum(values), 6)
        return result

    def electricity_reconciliation(
        self, daily_records: Mapping[str, Any], *, now: datetime
    ) -> dict[str, Any]:
        """Compare complete supplier days with recorded totals; never write them."""
        result = {}
        today = now.astimezone(_LONDON).date().isoformat()
        for kind, field in (
            ("electricity_import", "grid_import_kwh"),
            ("electricity_export", "grid_export_kwh"),
        ):
            comparisons = []
            for day, supplier in self.complete_day_totals(kind).items():
                if day >= today:
                    continue
                values = daily_records.get(day)
                recorded = values.get(field) if isinstance(values, Mapping) else None
                if (
                    isinstance(recorded, bool)
                    or not isinstance(recorded, (int, float))
                    or not isfinite(recorded)
                    or recorded < 0
                ):
                    recorded = None
                comparisons.append(
                    {
                        "date": day,
                        "supplier_kwh": supplier,
                        "recorded_kwh": recorded,
                        "supplier_minus_recorded_kwh": (
                            round(supplier - recorded, 6)
                            if recorded is not None
                            else None
                        ),
                    }
                )
            matched = [
                row
                for row in comparisons
                if row["supplier_minus_recorded_kwh"] is not None
            ]
            result[kind] = {
                "complete_supplier_days": len(comparisons),
                "comparable_recorded_days": len(matched),
                "missing_recorded_days": len(comparisons) - len(matched),
                "net_difference_kwh": (
                    round(sum(row["supplier_minus_recorded_kwh"] for row in matched), 6)
                    if matched
                    else None
                ),
                "recent_days": comparisons[-14:],
            }
        return {
            "scope": "read_only_supplier_vs_recorded_daily_energy",
            "kinds": result,
            "cost_or_roi_adjustment_authorised": False,
            "interval_gap_assignment_authorised": False,
        }

    def gas_quarantine_comparison(self) -> dict[str, Any]:
        """Compare only exact overlapping, non-conflicting gas intervals."""
        by_day = defaultdict(list)
        for key, raw in self.quarantined_gas.items():
            csv = self.rows.get(key)
            if (
                csv is None
                or key in self.conflicts
                or key in self.quarantined_gas_conflicts
            ):
                continue
            day = datetime.fromisoformat(key[1]).astimezone(_LONDON).date()
            by_day[day].append((raw["kwh"], csv["kwh"]))
        recent = []
        for day, pairs in sorted(by_day.items())[-14:]:
            automatic = sum(pair[0] for pair in pairs)
            reference = sum(pair[1] for pair in pairs)
            recent.append(
                {
                    "date": day.isoformat(),
                    "matched_intervals": len(pairs),
                    "nonzero_matched_intervals": sum(
                        left > 0 or right > 0 for left, right in pairs
                    ),
                    "automatic_kwh": round(automatic, 6),
                    "csv_kwh": round(reference, 6),
                    "difference_kwh": round(automatic - reference, 6),
                }
            )
        raw_by_day = defaultdict(list)
        for key, row in self.quarantined_gas.items():
            day = datetime.fromisoformat(key[1]).astimezone(_LONDON).date()
            raw_by_day[day.isoformat()].append((key, row["kwh"]))
        csv_days = self.complete_day_totals("gas")
        daily = []
        for day, pairs in sorted(raw_by_day.items())[-14:]:
            raw_total = round(sum(value for _, value in pairs), 6)
            conflicts = sum(key in self.quarantined_gas_conflicts for key, _ in pairs)
            reference = (
                self.gas_daily_reference.get(day)
                if day not in self.gas_daily_reference_conflicts
                else None
            )
            daily.append(
                {
                    "date": day,
                    "raw_intervals": len(pairs),
                    "raw_conflicts": conflicts,
                    "raw_first_seen_kwh": raw_total,
                    "complete_csv_day_kwh": csv_days.get(day),
                    "corroborated_daily_reference_kwh": reference,
                }
            )
        paired = []
        for key, row in sorted(self.quarantined_gas.items()):
            volume = row.get("consumption_m3")
            if volume is None or (volume == 0 and row["kwh"] == 0):
                continue
            csv = self.rows.get(key)
            paired.append(
                {
                    "start": row["start"],
                    "end": row["end"],
                    "automatic_kwh": row["kwh"],
                    "automatic_m3": volume,
                    "observed_kwh_per_m3": (
                        round(row["kwh"] / volume, 6) if volume > 0 else None
                    ),
                    "csv_kwh": (
                        csv["kwh"]
                        if csv is not None and key not in self.conflicts
                        else None
                    ),
                    "automatic_conflict": key in self.quarantined_gas_conflicts,
                }
            )
        return {
            "paired_nonzero_observations": len(paired),
            "recent_paired_nonzero_observations": paired[-48:],
            "conversion_validated": False,
            "recent_raw_days": daily,
            "matched_nonconflicting_intervals": sum(
                len(pairs) for pairs in by_day.values()
            ),
            "recent_overlap_days": recent,
            "automatic_gas_financially_usable": False,
        }

    def summary(self) -> dict[str, Any]:
        """Count missing half-hours without inventing zero usage or full days."""
        kinds = {}
        for kind in KINDS:
            rows = [row for key, row in self.rows.items() if key[0] == kind]
            usable = [row for row in rows if (kind, row["start"]) not in self.conflicts]
            starts = sorted(datetime.fromisoformat(row["start"]) for row in rows)
            by_day: dict[Any, list[dict[str, Any]]] = defaultdict(list)
            for row in usable:
                day = datetime.fromisoformat(row["start"]).astimezone(_LONDON).date()
                by_day[day].append(row)
            complete_days = 0
            daily_totals = {}
            for day, day_rows in sorted(by_day.items()):
                start = datetime.combine(day, datetime.min.time(), _LONDON)
                end = datetime.combine(
                    day + timedelta(days=1), datetime.min.time(), _LONDON
                )
                expected = int(
                    (end.astimezone(UTC) - start.astimezone(UTC)) / _HALF_HOUR
                )
                if len(day_rows) == expected:
                    complete_days += 1
                    daily_totals[day.isoformat()] = round(
                        sum(row["kwh"] for row in day_rows), 6
                    )
            expected_internal = (
                int((starts[-1] - starts[0]) / _HALF_HOUR) + 1 if starts else 0
            )
            kinds[kind] = {
                "retained_intervals": len(rows),
                "usable_intervals": len(usable),
                "conflicting_intervals": len(rows) - len(usable),
                "missing_or_conflicting_within_retained_span": (
                    expected_internal - len(usable)
                ),
                "complete_local_days": complete_days,
                "recent_complete_day_totals_kwh": dict(list(daily_totals.items())[-7:]),
                "first_start": starts[0].isoformat() if starts else None,
                "last_end": ((starts[-1] + _HALF_HOUR).isoformat() if starts else None),
                "source_counts": dict(Counter(row["source"] for row in usable)),
            }
        return {
            "scope": "separate_supplier_reported_half_hour_observations",
            "kinds": kinds,
            "gas_quarantine": {
                "status": "automatic_gas_unverified",
                "overlap_comparison": self.gas_quarantine_comparison(),
                "retained_raw_intervals": len(self.quarantined_gas),
                "conflicting_raw_intervals": len(self.quarantined_gas_conflicts),
                "recent_daily_reference_kwh": {
                    day: value
                    for day, value in sorted(self.gas_daily_reference.items())[-14:]
                    if day not in self.gas_daily_reference_conflicts
                },
                "daily_reference_conflicts": len(self.gas_daily_reference_conflicts),
                "daily_reference_is_not_supplier_settlement": True,
                "automatic_gas_financially_usable": False,
                "reference_converted_to_half_hours": False,
            },
            "missing_intervals_zero_filled": False,
            "existing_financial_ledger_modified": False,
            "hardware_write_authorised": False,
        }
