"""Home Assistant-independent commissioning evidence helpers.

These helpers analyse observation history and source metadata only. They do not
call Home Assistant services, create a hardware backend, or permit real inverter
writes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any

FOXESS_SITE_TELEMETRY_FIELDS: tuple[str, ...] = (
    "solar_power_kw",
    "house_load_kw",
    "grid_import_kw",
    "grid_export_kw",
)

FOXESS_REQUIRED_TELEMETRY_FIELDS: tuple[str, ...] = (
    "battery_soc",
    "battery_power_kw",
    *FOXESS_SITE_TELEMETRY_FIELDS,
)

FOXESS_POWER_UNIT_FIELDS: tuple[str, ...] = (
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


@dataclass(frozen=True, slots=True)
class UnitContractEvidence:
    """Evidence that raw FoxESS source units match KEMS conversion assumptions."""

    state: str
    ready: bool
    checked_fields: int
    required_fields: int
    observed_units: dict[str, str | None]
    missing_fields: tuple[str, ...]
    mismatched_fields: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a stable serialisable unit-contract payload."""
        return {
            "state": self.state,
            "ready": self.ready,
            "checked_fields": self.checked_fields,
            "required_fields": self.required_fields,
            "observed_units": dict(self.observed_units),
            "missing_fields": list(self.missing_fields),
            "mismatched_fields": list(self.mismatched_fields),
        }


@dataclass(frozen=True, slots=True)
class PowerBalanceEvidence:
    """Evidence that physical FoxESS flows obey a consistent whole-site balance."""

    state: str
    ready: bool
    samples: int
    eligible_samples: int
    balanced_samples: int
    balance_percent: float
    invalid_samples: int
    mean_absolute_residual_kw: float | None
    maximum_absolute_residual_kw: float | None
    absolute_tolerance_kw: float
    relative_tolerance_percent: float

    def to_dict(self) -> dict[str, Any]:
        """Return a stable serialisable physical-balance payload."""
        return {
            "state": self.state,
            "ready": self.ready,
            "samples": self.samples,
            "eligible_samples": self.eligible_samples,
            "balanced_samples": self.balanced_samples,
            "balance_percent": self.balance_percent,
            "invalid_samples": self.invalid_samples,
            "mean_absolute_residual_kw": self.mean_absolute_residual_kw,
            "maximum_absolute_residual_kw": self.maximum_absolute_residual_kw,
            "absolute_tolerance_kw": self.absolute_tolerance_kw,
            "relative_tolerance_percent": self.relative_tolerance_percent,
        }


@dataclass(frozen=True, slots=True)
class BatteryDirectionEvidence:
    """Read-only evidence for the FoxESS battery-power sign convention."""

    state: str
    ready: bool
    positive_is_discharge: bool | None
    evidence_samples: int
    positive_is_discharge_votes: int
    positive_is_charge_votes: int
    confidence_percent: float
    minimum_battery_power_kw: float
    minimum_residual_separation_kw: float

    def to_dict(self) -> dict[str, Any]:
        """Return a stable serialisable commissioning payload."""
        return {
            "state": self.state,
            "ready": self.ready,
            "positive_is_discharge": self.positive_is_discharge,
            "evidence_samples": self.evidence_samples,
            "positive_is_discharge_votes": self.positive_is_discharge_votes,
            "positive_is_charge_votes": self.positive_is_charge_votes,
            "confidence_percent": self.confidence_percent,
            "minimum_battery_power_kw": self.minimum_battery_power_kw,
            "minimum_residual_separation_kw": self.minimum_residual_separation_kw,
        }


@dataclass(frozen=True, slots=True)
class PhysicalShadowComparison:
    """Informational comparison between KEMS battery intent and FoxESS telemetry."""

    available: bool
    informational_only: bool
    target_charge_kw: float
    target_discharge_kw: float
    target_net_discharge_kw: float
    observed_charge_kw: float | None
    observed_discharge_kw: float | None
    observed_net_discharge_kw: float | None
    difference_kw: float | None
    tolerance_kw: float
    within_tolerance: bool | None
    observed_direction: str

    def to_dict(self) -> dict[str, Any]:
        """Return a stable serialisable physical-shadow payload."""
        return {
            "available": self.available,
            "informational_only": self.informational_only,
            "target_charge_kw": self.target_charge_kw,
            "target_discharge_kw": self.target_discharge_kw,
            "target_net_discharge_kw": self.target_net_discharge_kw,
            "observed_charge_kw": self.observed_charge_kw,
            "observed_discharge_kw": self.observed_discharge_kw,
            "observed_net_discharge_kw": self.observed_net_discharge_kw,
            "difference_kw": self.difference_kw,
            "tolerance_kw": self.tolerance_kw,
            "within_tolerance": self.within_tolerance,
            "observed_direction": self.observed_direction,
        }


def _normalised_unit(value: Any) -> str | None:
    """Return a compact lower-case unit label, or None when absent."""
    if value is None:
        return None
    unit = str(value).strip().casefold().replace(" ", "")
    return unit or None


def assess_foxess_unit_contract(
    source_units: Mapping[str, Any],
    *,
    battery_power_derived: bool = False,
    battery_required: bool = True,
) -> UnitContractEvidence:
    """Verify raw source units before KEMS treats FoxESS telemetry as evidence.

    Power sources may be W or kW because the provider explicitly normalises W
    to kW. Battery SOC must be percentage. A derived battery-power source must
    use volts and amps because KEMS multiplies those values directly.
    """
    expected: dict[str, set[str]] = {
        "solar_power_kw": {"w", "kw"},
        "house_load_kw": {"w", "kw"},
        "grid_import_kw": {"w", "kw"},
        "grid_export_kw": {"w", "kw"},
    }
    if battery_required:
        expected["battery_soc"] = {"%"}
        if battery_power_derived:
            expected.update(
                {
                    "battery_voltage": {"v"},
                    "battery_current": {"a"},
                }
            )
        else:
            expected["battery_power_kw"] = {"w", "kw"}

    observed = {field: _normalised_unit(source_units.get(field)) for field in expected}
    missing = tuple(sorted(field for field, unit in observed.items() if unit is None))
    mismatched = tuple(
        sorted(
            field
            for field, unit in observed.items()
            if unit is not None and unit not in expected[field]
        )
    )
    checked = len(expected) - len(missing)

    if missing:
        state = "unit_missing"
        ready = False
    elif mismatched:
        state = "unit_mismatch"
        ready = False
    else:
        state = "valid"
        ready = True

    return UnitContractEvidence(
        state=state,
        ready=ready,
        checked_fields=checked,
        required_fields=len(expected),
        observed_units=observed,
        missing_fields=missing,
        mismatched_fields=mismatched,
    )


def assess_foxess_telemetry_stability(
    records: tuple[Any, ...] | list[Any],
    *,
    expected_interval_seconds: float,
    battery_required: bool = True,
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
    required_fields = set(
        FOXESS_REQUIRED_TELEMETRY_FIELDS
        if battery_required
        else FOXESS_SITE_TELEMETRY_FIELDS
    )

    complete_samples = 0
    missing: set[str] = set()
    stale: set[str] = set()
    timestamps: list[Any] = []

    for record in recent:
        timestamp = getattr(record, "timestamp", None)
        if timestamp is not None:
            timestamps.append(timestamp)

        sample_missing = {
            field for field in required_fields if getattr(record, field, None) is None
        }
        sample_stale = set(getattr(record, "stale_fields", ()) or ()) & required_fields
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


def _battery_routing(
    raw_power_kw: float,
    *,
    positive_is_discharge: bool,
) -> tuple[float, float]:
    """Return positive charge and discharge magnitudes from signed battery power."""
    if positive_is_discharge:
        discharge = max(raw_power_kw, 0.0)
        charge = max(-raw_power_kw, 0.0)
    else:
        charge = max(raw_power_kw, 0.0)
        discharge = max(-raw_power_kw, 0.0)
    return charge, discharge


def infer_battery_power_convention_from_balance(
    records: tuple[Any, ...] | list[Any],
    *,
    minimum_evidence_samples: int = 3,
    minimum_battery_power_kw: float = 0.25,
    minimum_confidence_percent: float = 75.0,
    minimum_residual_separation_kw: float = 0.15,
    recent_sample_limit: int = 60,
) -> BatteryDirectionEvidence:
    """Infer battery sign from repeated whole-site conservation residuals.

    This is a fallback for large batteries whose integer SOC telemetry can take
    a long time to move. It never writes hardware and does not assume either
    sign. For each fresh sample with meaningful battery power KEMS evaluates
    both possible sign conventions and records a vote only when one convention
    produces a physically plausible site balance and is decisively better than
    the other. Ambiguous samples are ignored.
    """
    recent = list(records)[-max(int(recent_sample_limit), 1) :]
    required = set(FOXESS_POWER_UNIT_FIELDS)
    positive_is_discharge_votes = 0
    positive_is_charge_votes = 0
    minimum_power = max(float(minimum_battery_power_kw), 0.0)
    minimum_separation = max(float(minimum_residual_separation_kw), 0.0)

    for record in recent:
        if required & set(getattr(record, "stale_fields", ()) or ()):
            continue

        values: dict[str, float] = {}
        unusable = False
        for field in required:
            value = getattr(record, field, None)
            if value is None:
                unusable = True
                break
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                unusable = True
                break
            if not isfinite(numeric):
                unusable = True
                break
            values[field] = numeric
        if unusable:
            continue

        if any(
            values[field] < -0.05
            for field in (
                "solar_power_kw",
                "house_load_kw",
                "grid_import_kw",
                "grid_export_kw",
            )
        ):
            continue

        battery_power = values["battery_power_kw"]
        if abs(battery_power) < minimum_power:
            continue

        solar = max(values["solar_power_kw"], 0.0)
        house = max(values["house_load_kw"], 0.0)
        grid_import = max(values["grid_import_kw"], 0.0)
        grid_export = max(values["grid_export_kw"], 0.0)

        site_without_battery = solar + grid_import - house - grid_export
        positive_discharge_residual = abs(site_without_battery + battery_power)
        positive_charge_residual = abs(site_without_battery - battery_power)
        separation = abs(
            positive_discharge_residual - positive_charge_residual
        )

        throughput = max(
            solar + grid_import + abs(battery_power),
            house + grid_export + abs(battery_power),
            1.0,
        )
        plausible_residual = max(0.35, throughput * 0.15)
        decisive_separation = max(
            minimum_separation,
            abs(battery_power) * 0.5,
        )

        winner = min(positive_discharge_residual, positive_charge_residual)
        if winner > plausible_residual or separation < decisive_separation:
            continue

        if positive_discharge_residual < positive_charge_residual:
            positive_is_discharge_votes += 1
        elif positive_charge_residual < positive_discharge_residual:
            positive_is_charge_votes += 1

    evidence_samples = positive_is_discharge_votes + positive_is_charge_votes
    if evidence_samples:
        dominant = max(positive_is_discharge_votes, positive_is_charge_votes)
        confidence = round(100.0 * dominant / evidence_samples, 1)
    else:
        confidence = 0.0

    required_samples = max(int(minimum_evidence_samples), 1)
    required_confidence = max(float(minimum_confidence_percent), 0.0)
    if evidence_samples < required_samples:
        state = "collecting"
        ready = False
        detected: bool | None = None
    elif confidence < required_confidence:
        state = "ambiguous"
        ready = False
        detected = None
    else:
        state = "inferred"
        ready = True
        detected = positive_is_discharge_votes > positive_is_charge_votes

    return BatteryDirectionEvidence(
        state=state,
        ready=ready,
        positive_is_discharge=detected,
        evidence_samples=evidence_samples,
        positive_is_discharge_votes=positive_is_discharge_votes,
        positive_is_charge_votes=positive_is_charge_votes,
        confidence_percent=confidence,
        minimum_battery_power_kw=round(minimum_power, 3),
        minimum_residual_separation_kw=round(minimum_separation, 3),
    )


def assess_foxess_power_balance(
    records: tuple[Any, ...] | list[Any],
    *,
    positive_is_discharge: bool,
    battery_required: bool = True,
    minimum_samples: int = 12,
    minimum_balance_percent: float = 90.0,
    recent_sample_limit: int = 60,
    absolute_tolerance_kw: float = 0.75,
    relative_tolerance_percent: float = 15.0,
) -> PowerBalanceEvidence:
    """Verify repeated whole-site power conservation using physical observations.

    For every eligible sample KEMS compares physical sources (solar, grid import,
    battery discharge) with sinks (house, grid export, battery charge). The
    tolerance is the larger of an absolute allowance and a percentage of the
    observed site throughput, which accommodates asynchronous Modbus registers
    without hiding gross unit or sign errors.
    """
    recent = list(records)[-max(int(recent_sample_limit), minimum_samples, 1) :]
    residuals: list[float] = []
    balanced = 0
    invalid = 0
    required = set(
        FOXESS_REQUIRED_TELEMETRY_FIELDS
        if battery_required
        else FOXESS_SITE_TELEMETRY_FIELDS
    )

    for record in recent:
        if required & set(getattr(record, "stale_fields", ()) or ()):
            continue
        values: dict[str, float] = {}
        unusable = False
        for field in required:
            value = getattr(record, field, None)
            if value is None:
                unusable = True
                break
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                unusable = True
                break
            if not isfinite(numeric):
                unusable = True
                break
            values[field] = numeric
        if unusable:
            continue

        if battery_required and not 0.0 <= values["battery_soc"] <= 100.0:
            invalid += 1
            continue
        if any(
            values[field] < -0.05
            for field in (
                "solar_power_kw",
                "house_load_kw",
                "grid_import_kw",
                "grid_export_kw",
            )
        ):
            invalid += 1
            continue

        solar = max(values["solar_power_kw"], 0.0)
        house = max(values["house_load_kw"], 0.0)
        grid_import = max(values["grid_import_kw"], 0.0)
        grid_export = max(values["grid_export_kw"], 0.0)
        if battery_required:
            charge, discharge = _battery_routing(
                values["battery_power_kw"],
                positive_is_discharge=positive_is_discharge,
            )
        else:
            charge = 0.0
            discharge = 0.0
        sources = solar + grid_import + discharge
        sinks = house + grid_export + charge
        residual = sources - sinks
        throughput = max(sources, sinks, 1.0)
        tolerance = max(
            max(float(absolute_tolerance_kw), 0.0),
            throughput * max(float(relative_tolerance_percent), 0.0) / 100.0,
        )
        residuals.append(residual)
        if abs(residual) <= tolerance:
            balanced += 1

    eligible = len(residuals)
    balance_percent = round(100.0 * balanced / eligible, 1) if eligible else 0.0
    mean_residual = (
        round(sum(abs(value) for value in residuals) / eligible, 3)
        if eligible
        else None
    )
    maximum_residual = (
        round(max(abs(value) for value in residuals), 3) if eligible else None
    )

    if len(recent) < minimum_samples:
        state = "collecting"
        ready = False
    elif eligible < minimum_samples:
        state = "incomplete"
        ready = False
    elif balance_percent < minimum_balance_percent:
        state = "power_balance_mismatch"
        ready = False
    else:
        state = "balanced"
        ready = True

    return PowerBalanceEvidence(
        state=state,
        ready=ready,
        samples=len(recent),
        eligible_samples=eligible,
        balanced_samples=balanced,
        balance_percent=balance_percent,
        invalid_samples=invalid,
        mean_absolute_residual_kw=mean_residual,
        maximum_absolute_residual_kw=maximum_residual,
        absolute_tolerance_kw=round(max(float(absolute_tolerance_kw), 0.0), 3),
        relative_tolerance_percent=round(
            max(float(relative_tolerance_percent), 0.0), 1
        ),
    )


def compare_shadow_battery_target(
    control: Any,
    snapshot: Any,
    *,
    positive_is_discharge: bool,
    tolerance_kw: float = 0.5,
) -> PhysicalShadowComparison:
    """Compare KEMS battery intent with physical FoxESS battery telemetry.

    This is deliberately informational: before KEMS has a write-capable backend,
    the inverter is not expected to follow the shadow target. The comparison is
    evidence for commissioning and must never be interpreted as permission to
    control hardware.
    """
    target_charge = round(max(float(control.desired_charge_power_kw), 0.0), 3)
    target_discharge = round(
        max(float(control.desired_total_discharge_power_kw), 0.0), 3
    )
    target_net = round(target_discharge - target_charge, 3)
    tolerance = round(max(float(tolerance_kw), 0.0), 3)

    raw = getattr(snapshot, "battery_power_kw", None)
    stale = "battery_power_kw" in set(getattr(snapshot, "stale_fields", ()) or ())
    try:
        raw_numeric = None if raw is None else float(raw)
    except (TypeError, ValueError):
        raw_numeric = None

    if raw_numeric is None or not isfinite(raw_numeric) or stale:
        return PhysicalShadowComparison(
            available=False,
            informational_only=True,
            target_charge_kw=target_charge,
            target_discharge_kw=target_discharge,
            target_net_discharge_kw=target_net,
            observed_charge_kw=None,
            observed_discharge_kw=None,
            observed_net_discharge_kw=None,
            difference_kw=None,
            tolerance_kw=tolerance,
            within_tolerance=None,
            observed_direction="unavailable",
        )

    charge, discharge = _battery_routing(
        raw_numeric,
        positive_is_discharge=positive_is_discharge,
    )
    charge = round(charge, 3)
    discharge = round(discharge, 3)
    observed_net = round(discharge - charge, 3)
    difference = round(observed_net - target_net, 3)
    if discharge > 0.01:
        direction = "discharge"
    elif charge > 0.01:
        direction = "charge"
    else:
        direction = "idle"

    return PhysicalShadowComparison(
        available=True,
        informational_only=True,
        target_charge_kw=target_charge,
        target_discharge_kw=target_discharge,
        target_net_discharge_kw=target_net,
        observed_charge_kw=charge,
        observed_discharge_kw=discharge,
        observed_net_discharge_kw=observed_net,
        difference_kw=difference,
        tolerance_kw=tolerance,
        within_tolerance=abs(difference) <= tolerance,
        observed_direction=direction,
    )
