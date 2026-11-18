"""Read-only lifetime import/export counter candidates around missing samples.

Both sources may be HA integration-derived from sampled power; these checks
do not establish independent physical metering, supplier settlement, or the
energy consumed during the exact missing interval.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

ANCHOR_LEAD = timedelta(minutes=30)
ANCHOR_LAG = timedelta(minutes=30)
MAX_PLAUSIBLE_KW = 25.0
MAX_GAPS = 40


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _valid_rows(items: Sequence[Mapping[str, Any]]) -> list[tuple[datetime, float]]:
    result: list[tuple[datetime, float]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        at = _utc(item.get("reported_at"))
        value = item.get("kwh")
        if (
            at is None
            or not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not isfinite(value)
            or value < 0
        ):
            continue
        result.append((at, float(value)))
    return sorted(result)


def _pair(
    start: datetime, end: datetime, rows: list[tuple[datetime, float]]
) -> dict[str, Any]:
    before = [item for item in rows if start - ANCHOR_LEAD <= item[0] <= start]
    after = [item for item in rows if end <= item[0] <= end + ANCHOR_LAG]
    if not before or not after:
        return {
            "status": "no_bounded_anchor_pair",
            "bounded_pair_observed": False,
            "delta_candidate_kwh": None,
        }
    first = before[-1]
    last = after[0]
    elapsed = (last[0] - first[0]).total_seconds()
    delta = last[1] - first[1]
    if elapsed <= 0 or delta < -0.001:
        status = "reset_or_nonmonotonic"
    elif delta > MAX_PLAUSIBLE_KW * elapsed / 3600 + 0.25:
        status = "implausible_change"
    else:
        status = "plausible_counter_pair_unverified"
    return {
        "status": status,
        "bounded_pair_observed": True,
        "before_at": first[0].isoformat(),
        "after_at": last[0].isoformat(),
        "anchor_span_seconds": round(elapsed),
        "anchor_span_exceeds_unobserved_gap": True,
        "delta_candidate_kwh": round(delta, 5),
        "independent_physical_meter_verified": False,
        "usable_for_backfill": False,
    }


def meter_gap_anchor_evidence(
    *,
    gaps: Sequence[Mapping[str, Any]],
    import_lifetime_rows: Sequence[Mapping[str, Any]],
    export_lifetime_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Classify plausible counter anchors; never calculate gap-only kWh."""
    imported = _valid_rows(import_lifetime_rows)
    exported = _valid_rows(export_lifetime_rows)
    details: list[dict[str, Any]] = []
    for gap in list(gaps)[-MAX_GAPS:]:
        if not isinstance(gap, Mapping):
            continue
        start = _utc(gap.get("start"))
        end = _utc(gap.get("end"))
        if start is None or end is None or end <= start:
            continue
        details.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "import_counter": _pair(start, end, imported),
                "export_counter": _pair(start, end, exported),
                "exact_unobserved_interval_kwh": None,
                "physical_meter_completeness_verified": False,
                "eligible_for_energy_cost_or_reward_backfill": False,
            }
        )
    return {
        "scope": "read_only_lifetime_counter_anchor_candidates",
        "import_sample_count": len(imported),
        "export_sample_count": len(exported),
        "anchor_lead_minutes": 30,
        "anchor_lag_minutes": 30,
        "gap_rows": details,
        "two_way_physical_provenance_verified": False,
        "independent_supplier_meter_verified": False,
        "backfill_approved": False,
        "changes_to_cost_roi_dispatch": False,
        "note": (
            "Candidate register readings can be derived from HA power sampling. "
            "Even plausible counter deltas cover a larger span than the missing "
            "interval and cannot be assigned solely to downtime. Import AND "
            "export require independent meter provenance before backfill."
        ),
    }
