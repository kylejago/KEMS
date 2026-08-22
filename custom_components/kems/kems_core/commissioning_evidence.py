"""Home Assistant-independent commissioning evidence helpers.

These helpers analyse observation history only. They do not call Home Assistant
services, create a hardware backend, or permit real inverter writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FOXESS_REQUIRED_TELEMETRY_FIELDS: tuple[str, ...] = (
    "battery_soc",
    "battery_power_kw",
    "solar_power_kw",
    "house_load_kw",
    "grid_import_kw",
    "grid_export_kw",
)


@dataclass(frozen=True, slots=True)
class TelemetryStabilityEvidence:
    """Read-only evidence that physical telemetry has remained usable over time."""

    state: str
    ready: bool
    samples: int
    complete_samples: int
    completeness_percent: float
    observed_gaps: int
    maximum_gap_seconds: float | None
    allowed_gap_seconds: float
    missing_fields: tuple[str, ...]
    stale_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a stable serialisable commissioning payload."""
        return {
            "state": self.state,
            "ready": self.ready,
            "samples": self.samples,
            "complete_samples": self.complete_samples,
            "completeness_percent": self.completeness_percent,
            "observed_gaps": self.observed_gaps,
            "maximum_gap_seconds": self.maximum_gap_seconds,
            "allowed_gap_seconds": self.allowed_gap_seconds,
            "missing_fields": list(self.missing_fields),
            "stale_fields": list(self.stale_fields),
        }


def assess_foxess_telemetry_stability(
    records: tuple[Any, ...] | list[Any],
    *,
    expected_interval_seconds: float,
    minimum_samples: int = 12,
    minimum_completeness_percent: float = 95.0,
    recent_sample_limit: int = 60,
) -> TelemetryStabilityEvidence:
    """Assess recent FoxESS observation continuity without touching hardware.

    A commissioning-ready sample must contain all physical telemetry required by
    the KEMS observation contract and none of those fields may be marked stale.
    Once enough samples exist, continuity also requires the largest observation
    gap to stay within three configured scan intervals.
    """
    expected_interval = max(float(expected_interval_seconds), 1.0)
    allowed_gap = round(expected_interval * 3.0, 3)
    recent = list(records)[-max(int(recent_sample_limit), minimum_samples, 1) :]

    complete_samples = 0
    missing: set[str] = set()
    stale: set[str] = set()
    timestamps: list[Any] = []

    for record in recent:
        timestamp = getattr(record, "timestamp", None)
        if timestamp is not None:
            timestamps.append(timestamp)

        sample_missing = {
            field
            for field in FOXESS_REQUIRED_TELEMETRY_FIELDS
            if getattr(record, field, None) is None
        }
        sample_stale = set(getattr(record, "stale_fields", ()) or ()) & set(
            FOXESS_REQUIRED_TELEMETRY_FIELDS
        )
        missing.update(sample_missing)
        stale.update(sample_stale)
        if not sample_missing and not sample_stale:
            complete_samples += 1

    sample_count = len(recent)
    completeness = (
        round(100.0 * complete_samples / sample_count, 1) if sample_count else 0.0
    )

    gaps: list[float] = []
    for earlier, later in zip(timestamps, timestamps[1:], strict=False):
        try:
            gap = float((later - earlier).total_seconds())
        except (AttributeError, TypeError, ValueError):
            continue
        if gap > 0:
            gaps.append(gap)
    maximum_gap = round(max(gaps), 3) if gaps else None

    if sample_count < minimum_samples:
        state = "collecting"
        ready = False
    elif completeness < minimum_completeness_percent:
        state = "incomplete"
        ready = False
    elif len(timestamps) < minimum_samples:
        state = "timestamp_incomplete"
        ready = False
    elif maximum_gap is None or maximum_gap > allowed_gap:
        state = "unstable_interval"
        ready = False
    else:
        state = "stable"
        ready = True

    return TelemetryStabilityEvidence(
        state=state,
        ready=ready,
        samples=sample_count,
        complete_samples=complete_samples,
        completeness_percent=completeness,
        observed_gaps=len(gaps),
        maximum_gap_seconds=maximum_gap,
        allowed_gap_seconds=allowed_gap,
        missing_fields=tuple(sorted(missing)),
        stale_fields=tuple(sorted(stale)),
    )
