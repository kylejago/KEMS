"""Idempotent, separate supplier interval evidence; never financial dispatch."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
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
    return {
        "kind": kind,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "kwh": energy,
        "source": source,
    }


class SupplierIntervalLedger:
    """Preserve first-seen observations and quarantine conflicting intervals."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.conflicts: set[tuple[str, str]] = set()

    def ingest(
        self, rows: Iterable[Any], *, source: str, now: datetime
    ) -> bool:
        changed = False
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            row = normalise_interval(raw, source=source, now=now)
            if row is None:
                continue
            key = (row["kind"], row["start"])
            previous = self.rows.get(key)
            if previous is None:
                self.rows[key] = row
                changed = True
            elif (
                abs(previous["kwh"] - row["kwh"]) > 0.000001
                and key not in self.conflicts
            ):
                self.conflicts.add(key)
                changed = True
        return changed

    def dump(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "rows": list(self.rows.values()),
            "conflicts": [list(key) for key in sorted(self.conflicts)],
        }

    def restore(self, data: Any, *, now: datetime) -> None:
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            return
        for row in data.get("rows") or []:
            if isinstance(row, dict):
                self.ingest([row], source=row.get("source"), now=now)
        for item in data.get("conflicts") or []:
            if isinstance(item, list) and len(item) == 2:
                key = tuple(item)
                if key in self.rows:
                    self.conflicts.add(key)

    def summary(self) -> dict[str, Any]:
        """Count missing half-hours without inventing zero usage or full days."""
        kinds = {}
        for kind in KINDS:
            rows = [row for key, row in self.rows.items() if key[0] == kind]
            usable = [
                row for row in rows if (kind, row["start"]) not in self.conflicts
            ]
            starts = sorted(datetime.fromisoformat(row["start"]) for row in rows)
            counts = Counter(
                datetime.fromisoformat(row["start"]).astimezone(_LONDON).date()
                for row in usable
            )
            complete_days = 0
            for day, count in counts.items():
                start = datetime.combine(day, datetime.min.time(), _LONDON)
                end = datetime.combine(
                    day + timedelta(days=1), datetime.min.time(), _LONDON
                )
                expected = int(
                    (end.astimezone(UTC) - start.astimezone(UTC)) / _HALF_HOUR
                )
                complete_days += count == expected
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
                "first_start": starts[0].isoformat() if starts else None,
                "last_end": (
                    (starts[-1] + _HALF_HOUR).isoformat() if starts else None
                ),
                "source_counts": dict(Counter(row["source"] for row in usable)),
            }
        return {
            "scope": "separate_supplier_reported_half_hour_observations",
            "kinds": kinds,
            "missing_intervals_zero_filled": False,
            "existing_financial_ledger_modified": False,
            "hardware_write_authorised": False,
        }
