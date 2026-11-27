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


def supplier_cost_rows(kind, attributes):
    """Extract actual provider charge rows, not rates inferred from daily totals."""
    if (
        kind not in ELECTRICITY
        or not isinstance(attributes, Mapping)
        or attributes.get("unit_of_measurement") != "GBP"
        or attributes.get("is_export") is not (kind == "electricity_export")
        or not isinstance(attributes.get("charges"), list)
    ):
        return []
    result = []
    for row in attributes["charges"]:
        if not isinstance(row, Mapping):
            continue
        cost = _finite(row.get("raw_cost"))
        if cost is None or not isfinite(cost * 100):
            continue
        result.append(
            {
                "kind": kind,
                "start": row.get("start"),
                "end": row.get("end"),
                "kwh": row.get("consumption"),
                "charge_pence": cost * 100,
            }
        )
    return result


class SupplierChargeEvidence:
    """First-seen estimates with independent energy matching and conflict checks."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.conflicts: set[tuple[str, str, str]] = set()

    def ingest(self, rows: Iterable[Any], *, source: str, now: datetime) -> bool:
        changed = False
        if source not in ("octopus_csv", "octopus_integration"):
            return False
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
        self,
        energy,
        daily_records: Mapping[str, Any],
        *,
        now: datetime,
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
                expected = int(
                    (end.astimezone(UTC) - start.astimezone(UTC)) / _HALF_HOUR
                )
                if len(charges) != expected:
                    continue
                if commissioned is None or day <= commissioned:
                    before_commissioning += 1
                    continue
                value = round(sum(charges), 6)
                stored = daily_records.get(day.isoformat())
                recorded = (
                    _finite(stored.get(field)) if isinstance(stored, Mapping) else None
                )
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
                row
                for row in comparisons
                if row["supplier_minus_recorded_pence"] is not None
            ]
            complete_energy_days = {
                day
                for day in energy.complete_day_totals(kind)
                if commissioned is not None
                and commissioned.isoformat() < day < today.isoformat()
            }
            missing_priced_days = sorted(
                complete_energy_days - {row["date"] for row in comparisons}
            )
            result[kind] = {
                "complete_energy_post_commissioning_days": len(complete_energy_days),
                "complete_energy_days_missing_valid_prices": len(missing_priced_days),
                "recent_missing_priced_dates": missing_priced_days[-14:],
                "missing_priced_dates": missing_priced_days,
                "complete_priced_post_commissioning_days": len(comparisons),
                "excluded_before_or_unknown_commissioning_days": before_commissioning,
                "comparable_days": len(matched),
                "supplier_estimate_on_comparable_days_pence": (
                    round(sum(row["supplier_estimate_pence"] for row in matched), 6)
                    if matched
                    else None
                ),
                "recorded_on_comparable_days_pence": (
                    round(sum(row["recorded_pence"] for row in matched), 6)
                    if matched
                    else None
                ),
                "difference_pence": (
                    round(
                        sum(row["supplier_minus_recorded_pence"] for row in matched), 6
                    )
                    if matched
                    else None
                ),
                "recent_days": comparisons[-14:],
            }
        return {
            "scope": "supplier_estimated_gross_energy_charge_comparison",
            "retained_charge_observations": len(self.rows),
            "unmatched_or_conflicted_intervals": invalid,
            "financial_commissioning_date": (
                commissioned.isoformat() if commissioned else None
            ),
            "kinds": result,
            "standing_charges_and_event_rewards_excluded": True,
            "supplier_settlement_verified": False,
            "roi_or_ledger_write_authorised": False,
        }


def exact_event_meter_totals(
    energy, start: datetime, end: datetime
) -> dict[str, Any] | None:
    """No partial half-hours, missing meter readings, or implicit zero export."""
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or end <= start
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
            if row is None or key in energy.conflicts or _utc(row["end"]) != following:
                return None
            totals[kind] += row["kwh"]
        cursor = following
    return totals


def exact_completed_baseline(
    attributes: Any, start: datetime, end: datetime
) -> float | None:
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
            left is None
            or right is None
            or not start <= left < right <= end
            or value is None
            or value < 0
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


def _partial_baseline_rows(attributes, start, end):
    """Retain only valid exact half-hours, never incomplete calculations."""
    if not isinstance(attributes, Mapping):
        return {}
    rows = attributes.get("baselines")
    if not isinstance(rows, list):
        return {}
    result = {}
    for row in rows:
        if not isinstance(row, Mapping):
            return {}
        left, right = _utc(row.get("start")), _utc(row.get("end"))
        value = _finite(row.get("baseline"))
        if (
            left is None
            or right is None
            or not start <= left < right <= end
            or right - left != _HALF_HOUR
            or (left - start) % _HALF_HOUR
        ):
            return {}
        if row.get("is_incomplete_calculation") is not False:
            continue
        if value is None or value < 0 or left.isoformat() in result:
            return {}
        result[left.isoformat()] = value
    # When every row is valid, respect any provider total as well.
    reported = _finite(attributes.get("total_baseline"))
    if (
        len(result) == len(rows)
        and reported is not None
        and abs(reported - sum(result.values())) > 0.001
    ):
        return {}
    return result


def _complete_retained_rows(rows, start, end):
    if end <= start or end - start > timedelta(hours=24):
        return None
    cursor = start
    total = 0.0
    while cursor < end:
        value = _finite(rows.get(cursor.isoformat()))
        if value is None or value < 0 or cursor + _HALF_HOUR > end:
            return None
        total += value
        cursor += _HALF_HOUR
    if len(rows) != int((end - start) / _HALF_HOUR):
        return None
    return total


def capture_completed_baseline(
    event: Mapping[str, Any],
    import_attrs: Any,
    export_attrs: Any,
    *,
    now: datetime,
    points_per_kwh: Any = None,
    allow_partial: bool = False,
) -> dict[str, Any] | None:
    """Retain exact baseline windows even before meter readings arrive."""
    start, end = _utc(event.get("session_start")), _utc(event.get("session_end"))
    event_id = event.get("session_id")
    if (
        event.get("available") is not True
        or not event_id
        or start is None
        or end is None
        or not start < end <= now
    ):
        return None
    imported = exact_completed_baseline(import_attrs, start, end)
    exported = exact_completed_baseline(export_attrs, start, end)
    if not allow_partial and (imported is None or exported is None):
        return None
    rate = _finite(points_per_kwh)
    return {
        "session_id": str(event_id),
        "session_start": start.isoformat(),
        "session_end": end.isoformat(),
        "import_baseline_kwh": imported,
        "export_baseline_kwh": exported,
        "octopoints_per_kwh": rate if rate is not None and rate >= 0 else None,
        "import_baseline_rows": _partial_baseline_rows(import_attrs, start, end),
        "export_baseline_rows": _partial_baseline_rows(export_attrs, start, end),
    }


def capture_joined_baseline(
    event: Mapping[str, Any],
    import_attrs: Any,
    export_attrs: Any,
    *,
    now: datetime,
    retain_event_identity: bool = False,
) -> dict[str, Any] | None:
    """Preserve exact joined-event baselines before the provider replaces them."""
    start, end = _utc(event.get("start")), _utc(event.get("end"))
    event_id = event.get("id")
    if (
        not event_id
        or start is None
        or end is None
        or not start < end
        or start > now + timedelta(days=1)
        or end < now - timedelta(days=1)
        or end - start > timedelta(hours=24)
    ):
        return None
    imported = exact_completed_baseline(import_attrs, start, end)
    exported = exact_completed_baseline(export_attrs, start, end)
    import_rows = _partial_baseline_rows(import_attrs, start, end)
    export_rows = _partial_baseline_rows(export_attrs, start, end)
    if (
        not retain_event_identity
        and imported is None
        and exported is None
        and not import_rows
        and not export_rows
    ):
        return None
    rate = _finite(event.get("octopoints_per_kwh"))
    return {
        "session_id": str(event_id),
        "session_start": start.isoformat(),
        "session_end": end.isoformat(),
        "import_baseline_kwh": imported,
        "export_baseline_kwh": exported,
        "octopoints_per_kwh": rate if rate is not None and rate >= 0 else None,
        "import_baseline_rows": import_rows,
        "export_baseline_rows": export_rows,
    }


def recover_historical_baselines(events, attributes, direction):
    """Recover only explicitly complete baseline rows for known completed events."""
    if direction not in ("import", "export") or not isinstance(attributes, Mapping):
        return []
    baselines = attributes.get("baselines")
    if not isinstance(baselines, list) or not baselines:
        return []
    result = []
    for event in events:
        start, end = _utc(event.get("session_start")), _utc(event.get("session_end"))
        if start is None or end is None or not start < end:
            continue
        rows = _partial_baseline_rows(attributes, start, end)
        if not rows:
            continue
        evidence = {
            "session_id": event["session_id"],
            "session_start": event["session_start"],
            "session_end": event["session_end"],
            "import_baseline_kwh": None,
            "export_baseline_kwh": None,
            "octopoints_per_kwh": None,
            "import_baseline_rows": {},
            "export_baseline_rows": {},
        }
        evidence[f"{direction}_baseline_rows"] = rows
        evidence[f"{direction}_baseline_kwh"] = _complete_retained_rows(
            rows, start, end
        )
        result.append(evidence)
    return result


def merge_completed_baseline(
    prior: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge independently exact event evidence without overwriting conflicts."""
    if prior.get("conflict"):
        return dict(prior)
    merged = dict(prior)
    for key in ("session_id", "session_start", "session_end"):
        if prior.get(key) != evidence.get(key):
            return {**prior, "conflict": True}
    for key in (
        "import_baseline_kwh",
        "export_baseline_kwh",
        "octopoints_per_kwh",
    ):
        old, new = prior.get(key), evidence.get(key)
        if new is None:
            continue
        if old is not None and old != new:
            return {**prior, "conflict": True}
        merged[key] = new
    start = _utc(merged.get("session_start"))
    end = _utc(merged.get("session_end"))
    if start is None or end is None:
        return {**prior, "conflict": True}
    for direction in ("import", "export"):
        key = f"{direction}_baseline_rows"
        total_key = f"{direction}_baseline_kwh"
        rows = dict(prior.get(key) or {})
        for stamp, value in (evidence.get(key) or {}).items():
            if stamp in rows and abs(rows[stamp] - value) > 0.000001:
                return {**prior, "conflict": True}
            rows[stamp] = value
        merged[key] = rows
        total = _complete_retained_rows(rows, start, end)
        if total is not None:
            old = merged.get(total_key)
            if old is not None and abs(old - total) > 0.001:
                return {**prior, "conflict": True}
            if old is None:
                merged[total_key] = total
    return merged


def completed_power_down_estimate(
    energy, baseline: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate retained baseline against current non-conflicting meter evidence."""
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
    if start is None or end is None or start >= end:
        result["status"] = "invalid_retained_baseline"
        return result
    actual = exact_event_meter_totals(energy, start, end)
    if actual is not None:
        result["supplier_import_kwh"] = actual["electricity_import"]
        result["supplier_export_kwh"] = actual["electricity_export"]
    if imported is None or exported is None:
        result["status"] = "awaiting_exact_baseline_evidence"
        return result
    if min(imported, exported) < 0:
        result["status"] = "invalid_retained_baseline"
        return result
    if actual is None:
        return result
    reduction = max(
        imported
        - exported
        - actual["electricity_import"]
        + actual["electricity_export"],
        0.0,
    )
    rate = _finite(baseline.get("octopoints_per_kwh"))
    result.update(
        {
            "supplier_import_kwh": actual["electricity_import"],
            "supplier_export_kwh": actual["electricity_export"],
            "estimated_rewardable_reduction_kwh": round(reduction, 6),
            "estimated_bonus_pence": (
                round(reduction * rate / 8, 6)
                if rate is not None and rate >= 0
                else None
            ),
            "status": (
                "unsettled_event_estimate"
                if rate is not None and rate >= 0
                else "matched_energy_rate_unavailable"
            ),
        }
    )
    return result


def baseline_capture_diagnostic(attributes, start, end):
    """Explain rejected rows without treating incomplete estimates as valid."""
    attributes = attributes if isinstance(attributes, Mapping) else {}
    rows = attributes.get("baselines")
    valid = _partial_baseline_rows(attributes, start, end)
    rows = rows if isinstance(rows, list) else []
    return {
        "rows_reported": len(rows),
        "rows_explicitly_incomplete": sum(
            isinstance(row, Mapping) and row.get("is_incomplete_calculation") is True
            for row in rows
        ),
        "rows_without_explicit_complete_flag": sum(
            isinstance(row, Mapping)
            and row.get("is_incomplete_calculation") is not False
            and row.get("is_incomplete_calculation") is not True
            for row in rows
        ),
        "accepted_half_hours": len(valid),
        "exact_total_available": (
            exact_completed_baseline(attributes, start, end) is not None
        ),
        "source_period_start": (
            stamp.isoformat()
            if (stamp := _utc(attributes.get("start"))) is not None
            else None
        ),
        "source_period_end": (
            stamp.isoformat()
            if (stamp := _utc(attributes.get("end"))) is not None
            else None
        ),
        "supplier_settlement_verified": False,
    }
