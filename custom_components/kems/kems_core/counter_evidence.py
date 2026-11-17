"""Conservative, read-only cumulative import-counter validation evidence.

A sequence of fresh numeric HA states is NOT proof of an independently
metered cumulative register: source provenance, restart/reset history,
time anchoring, physical plausibility and supplier evidence remain separate.
Never use these records for charge, dispatch, ROI or historical backfill.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Mapping

MAX_SAMPLES_PER_CANDIDATE = 1536
MIN_SAMPLE_SPACING_SECONDS = 900
MAX_SAMPLE_AGE_SECONDS = 180
MAX_HISTORY_DAYS = 30
PLAUSIBILITY_ONLY_KW = 25.0
EPSILON_KWH = 0.001


def counter_observation(
    *,
    label: str,
    entity_id: str,
    state: Any | None,
    now: datetime,
) -> tuple[dict[str, Any] | None, str]:
    """Accept a fresh, well-formed report, with no physical-meter authority."""
    if now.tzinfo is None:
        return None, "invalid_capture_time"
    if state is None:
        return None, "not_available"
    raw = getattr(state, "state", None)
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None, "non_numeric"
    if not isfinite(value) or value < 0:
        return None, "invalid_value"
    attrs = getattr(state, "attributes", None) or {}
    if attrs.get("unit_of_measurement") != "kWh":
        return None, "wrong_unit"
    if attrs.get("state_class") not in {"total", "total_increasing"}:
        return None, "not_cumulative_class"
    reported = getattr(state, "last_reported", None) or getattr(
        state, "last_updated", None
    )
    if not isinstance(reported, datetime) or reported.tzinfo is None:
        return None, "missing_report_timestamp"
    age = (now - reported).total_seconds()
    if age < -15:
        return None, "future_report_timestamp"
    if age > MAX_SAMPLE_AGE_SECONDS:
        return None, "stale_counter_report"
    return (
        {
            "label": label,
            "entity_id": entity_id,
            "reported_at": reported.astimezone(UTC).isoformat(),
            "observed_at": now.astimezone(UTC).isoformat(),
            "kwh": round(value, 6),
        },
        "fresh_observation_only",
    )


def _parse_instant(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        result = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return result.astimezone(UTC) if result.tzinfo is not None else None


def _validate_row(
    row: Any, *, label: str, entity_id: str, now: datetime
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    if row.get("label") != label or row.get("entity_id") != entity_id:
        return None
    reported = _parse_instant(row.get("reported_at"))
    observed = _parse_instant(row.get("observed_at"))
    if reported is None or observed is None:
        return None
    if (
        reported > observed + timedelta(seconds=15)
        or observed > now + timedelta(seconds=15)
        or observed < now - timedelta(days=MAX_HISTORY_DAYS)
    ):
        return None
    value = row.get("kwh")
    if not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        return None
    return {
        "label": label,
        "entity_id": entity_id,
        "reported_at": reported.isoformat(),
        "observed_at": observed.isoformat(),
        "kwh": round(value, 6),
    }


class CounterEvidenceSeries:
    """Bounded in-memory time series, explicitly never authorised for backfill."""

    def __init__(self, source_entity_id: str) -> None:
        self.source_entity_id = source_entity_id
        self.entities = {
            "lifetime_total": source_entity_id + "_energy_total",
            "daily_total": source_entity_id + "_energy_today",
        }
        self.rows: dict[str, list[dict[str, Any]]] = {
            label: [] for label in self.entities
        }
        self.last_rejection: dict[str, str | None] = {
            label: None for label in self.entities
        }

    def restore(self, payload: Any, *, now: datetime) -> None:
        """Ignore foreign sources and corrupt or expired rows without raising."""
        if not isinstance(payload, Mapping):
            return
        if payload.get("source_entity_id") != self.source_entity_id:
            return
        stored = payload.get("candidates")
        if not isinstance(stored, Mapping):
            return
        for label, entity_id in self.entities.items():
            items = stored.get(label)
            if not isinstance(items, list):
                continue
            approved: list[dict[str, Any]] = []
            for row in items:
                checked = _validate_row(row, label=label, entity_id=entity_id, now=now)
                if checked is not None:
                    approved.append(checked)
            approved.sort(key=lambda row: row["reported_at"])
            # Keep only one observation per actual report timestamp.
            unique = {row["reported_at"]: row for row in approved}
            self.rows[label] = list(unique.values())[-MAX_SAMPLES_PER_CANDIDATE:]

    def observe(self, hass: Any, *, now: datetime) -> bool:
        """Inspect only configured counters; never mutate Home Assistant."""
        if not self.source_entity_id:
            return False
        changed = False
        for label, entity_id in self.entities.items():
            raw = hass.states.get(entity_id)
            row, reason = counter_observation(
                label=label, entity_id=entity_id, state=raw, now=now
            )
            self.last_rejection[label] = None if row is not None else reason
            if row is None:
                continue
            history = self.rows[label]
            if history:
                if row["reported_at"] <= history[-1]["reported_at"]:
                    continue
                previous_capture = _parse_instant(history[-1]["observed_at"])
                if (
                    previous_capture is not None
                    and (now - previous_capture).total_seconds()
                    < MIN_SAMPLE_SPACING_SECONDS
                ):
                    continue
            history.append(row)
            if len(history) > MAX_SAMPLES_PER_CANDIDATE:
                del history[:-MAX_SAMPLES_PER_CANDIDATE]
            changed = True
        return changed

    def payload(self) -> dict[str, Any]:
        """Versioned, small, source-bound store payload."""
        return {
            "schema_version": 1,
            "source_entity_id": self.source_entity_id,
            "candidates": {label: list(rows) for label, rows in self.rows.items()},
        }

    def status(self) -> dict[str, Any]:
        """Report monotonicity and plausibility, never physical authority."""
        outcomes: dict[str, Any] = {}
        for label, rows in self.rows.items():
            positive = flat = resets = implausible = 0
            growth = 0.0
            longest = 0
            for first, second in zip(rows, rows[1:], strict=False):
                earlier = _parse_instant(first["reported_at"])
                later = _parse_instant(second["reported_at"])
                if earlier is None or later is None:
                    continue
                seconds = (later - earlier).total_seconds()
                if seconds <= 0:
                    continue
                longest = max(longest, round(seconds))
                delta = second["kwh"] - first["kwh"]
                if delta < -EPSILON_KWH:
                    # A daily_total reset can be natural at midnight, but
                    # an unknown reset never supplies a restart-gap delta.
                    resets += 1
                elif delta <= EPSILON_KWH:
                    flat += 1
                elif delta > PLAUSIBILITY_ONLY_KW * seconds / 3600 + 0.25:
                    implausible += 1
                else:
                    positive += 1
                    growth += delta
            outcomes[label] = {
                "entity_id": self.entities[label],
                "fresh_report_samples": len(rows),
                "first_reported_at": rows[0]["reported_at"] if rows else None,
                "last_reported_at": rows[-1]["reported_at"] if rows else None,
                "last_observation_rejection": self.last_rejection[label],
                "nonnegative_plausible_delta_pairs": positive,
                "flat_pairs": flat,
                "reset_or_decrease_pairs": resets,
                "implausible_delta_pairs": implausible,
                "positive_plausible_delta_kwh": round(growth, 4),
                "longest_report_interval_seconds": longest,
                "physical_meter_provenance_verified": False,
                "independent_meter_delta_verified": False,
                "restart_gap_delta_usable": False,
            }
        return {
            "scope": "read_only_future_counter_reports",
            "source_power_entity": self.source_entity_id,
            "candidates": outcomes,
            "max_samples_per_candidate": MAX_SAMPLES_PER_CANDIDATE,
            "minimum_capture_spacing_seconds": MIN_SAMPLE_SPACING_SECONDS,
            "max_capture_age_seconds": MAX_SAMPLE_AGE_SECONDS,
            "plausibility_only_max_kw": PLAUSIBILITY_ONLY_KW,
            "candidate_plausibility_is_not_physical_meter_proof": True,
            "backfill_approved": False,
            "refund_or_roi_credit_authority": False,
            "physical_control_dependency": False,
            "warning": (
                "Even monotonic, plausible HA counter states may be derived "
                "from the same power samples and do not recover missing "
                "supplier-metered intervals. No historical kWh or rewards "
                "are written by this evidence trail."
            ),
        }
