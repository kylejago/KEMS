"""Home Assistant-independent commissioning evidence helpers.

These helpers analyse observation history and source metadata only. They do not
call Home Assistant services, create a hardware backend, or permit real inverter
writes.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Any

from .foxess_ac_balance import (
    assess_foxess_ac_ct_transition,
    assess_foxess_ac_side_sample,
)

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
    startup_empty_samples_excluded: int = 0

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
            "startup_empty_samples_excluded": self.startup_empty_samples_excluded,
        }


@dataclass(frozen=True, slots=True)
class BatteryDirectionObservation:
    """One read-only observation used to prove the battery power sign convention."""

    timestamp: Any
    battery_power_kw: float | None
    battery_soc: float | None = None
    battery_energy_remaining_kwh: float | None = None
    battery_charge_today_kwh: float | None = None
    battery_discharge_today_kwh: float | None = None


@dataclass(frozen=True, slots=True)
class BatteryDirectionEvidence:
    """Evidence that signed battery power agrees with physical energy movement."""

    state: str
    ready: bool
    positive_is_discharge: bool | None
    evidence_samples: int
    confidence_percent: float
    positive_is_discharge_votes: int
    positive_is_charge_votes: int
    basis_counts: tuple[tuple[str, int], ...]
    minimum_power_kw: float

    def to_dict(self) -> dict[str, Any]:
        """Return a stable serialisable battery-direction payload."""
        return {
            "state": self.state,
            "ready": self.ready,
            "positive_is_discharge": self.positive_is_discharge,
            "evidence_samples": self.evidence_samples,
            "confidence_percent": self.confidence_percent,
            "positive_is_discharge_votes": self.positive_is_discharge_votes,
            "positive_is_charge_votes": self.positive_is_charge_votes,
            "basis_counts": dict(self.basis_counts),
            "minimum_power_kw": self.minimum_power_kw,
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
    # Last eight mismatches only; purely diagnostic and never used for readiness.
    failed_samples: tuple[dict[str, Any], ...] = ()
    # AC analysis is informational only: calculated load can make it circular.
    ac_side_audit: dict[str, Any] | None = None

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
            "failed_samples": list(self.failed_samples),
            "ac_side_audit": dict(self.ac_side_audit or {}),
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
    recent_limit = max(int(recent_sample_limit), minimum_samples, 1)
    all_records = list(records)
    recent = all_records[-recent_limit:]
    required_fields = set(
        FOXESS_REQUIRED_TELEMETRY_FIELDS
        if battery_required
        else FOXESS_SITE_TELEMETRY_FIELDS
    )

    # HA can emit one all-empty physical snapshot when this commissioning
    # session starts, before the first FoxESS readings populate. That
    # snapshot is not valid evidence and must not poison a subsequent
    # physically complete 12+ sample qualification. This exception applies
    # ONLY to the first record of the actual session, NEVER to the first
    # record of a rolling 60-sample slice or a later telemetry dropout.
    # Partial and stale first observations are not exempt. The ordinary
    # minimum-sample, 95% completeness and timing gates still apply.
    startup_empty_samples_excluded = 0
    if (
        len(all_records) <= recent_limit
        and recent
        and all(getattr(recent[0], field, None) is None for field in required_fields)
        and not (set(getattr(recent[0], "stale_fields", ()) or ()) & required_fields)
    ):
        recent = recent[1:]
        startup_empty_samples_excluded = 1

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
        startup_empty_samples_excluded=startup_empty_samples_excluded,
    )


def assess_battery_power_direction(
    records: tuple[Any, ...] | list[Any],
    *,
    minimum_power_kw: float = 0.25,
    minimum_evidence_samples: int = 2,
    minimum_confidence_percent: float = 75.0,
    minimum_energy_delta_kwh: float = 0.002,
    minimum_soc_delta_percent: float = 0.2,
) -> BatteryDirectionEvidence:
    """Infer the signed battery-power convention from fresh physical movement.

    Evidence is deliberately session-scoped by the caller. Prefer BMS remaining
    energy because it can move long before a large battery changes one whole SOC
    percentage point. If that source is unavailable or unchanged, use the FoxESS
    daily charge/discharge energy counters, then fall back to SOC movement.

    A pair contributes at most one vote and only while average battery power is
    above the commissioning threshold. Counter resets are ignored.
    """
    recent = list(records)[-360:]
    positive_is_discharge_votes = 0
    positive_is_charge_votes = 0
    basis_counts: dict[str, int] = {
        "bms_energy_remaining": 0,
        "daily_energy_counters": 0,
        "soc": 0,
    }

    def numeric(record: Any, name: str) -> float | None:
        value = getattr(record, name, None)
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if isfinite(number) else None

    for earlier, later in zip(recent, recent[1:], strict=False):
        try:
            gap = float((later.timestamp - earlier.timestamp).total_seconds())
        except (AttributeError, TypeError, ValueError):
            continue
        if gap <= 0 or gap > 20 * 60:
            continue

        earlier_power = numeric(earlier, "battery_power_kw")
        later_power = numeric(later, "battery_power_kw")
        if earlier_power is None or later_power is None:
            continue
        average_power = (earlier_power + later_power) / 2.0
        if abs(average_power) < minimum_power_kw:
            continue

        physical_direction: str | None = None
        basis: str | None = None

        earlier_remaining = numeric(earlier, "battery_energy_remaining_kwh")
        later_remaining = numeric(later, "battery_energy_remaining_kwh")
        if earlier_remaining is not None and later_remaining is not None:
            delta_remaining = later_remaining - earlier_remaining
            if abs(delta_remaining) >= minimum_energy_delta_kwh:
                physical_direction = "discharge" if delta_remaining < 0 else "charge"
                basis = "bms_energy_remaining"

        if physical_direction is None:
            earlier_charge = numeric(earlier, "battery_charge_today_kwh")
            later_charge = numeric(later, "battery_charge_today_kwh")
            earlier_discharge = numeric(earlier, "battery_discharge_today_kwh")
            later_discharge = numeric(later, "battery_discharge_today_kwh")
            charge_delta = (
                later_charge - earlier_charge
                if earlier_charge is not None and later_charge is not None
                else None
            )
            discharge_delta = (
                later_discharge - earlier_discharge
                if earlier_discharge is not None and later_discharge is not None
                else None
            )
            charge_moved = (
                charge_delta is not None and charge_delta >= minimum_energy_delta_kwh
            )
            discharge_moved = (
                discharge_delta is not None
                and discharge_delta >= minimum_energy_delta_kwh
            )
            counter_reset = (
                charge_delta is not None and charge_delta < -minimum_energy_delta_kwh
            ) or (
                discharge_delta is not None
                and discharge_delta < -minimum_energy_delta_kwh
            )
            if not counter_reset and charge_moved != discharge_moved:
                physical_direction = "charge" if charge_moved else "discharge"
                basis = "daily_energy_counters"

        if physical_direction is None:
            earlier_soc = numeric(earlier, "battery_soc")
            later_soc = numeric(later, "battery_soc")
            if earlier_soc is not None and later_soc is not None:
                delta_soc = later_soc - earlier_soc
                if abs(delta_soc) >= minimum_soc_delta_percent:
                    physical_direction = "discharge" if delta_soc < 0 else "charge"
                    basis = "soc"

        if physical_direction is None or basis is None:
            continue

        positive_is_discharge = (
            physical_direction == "discharge" and average_power > 0
        ) or (physical_direction == "charge" and average_power < 0)
        if positive_is_discharge:
            positive_is_discharge_votes += 1
        else:
            positive_is_charge_votes += 1
        basis_counts[basis] += 1

    total = positive_is_discharge_votes + positive_is_charge_votes
    dominant = max(positive_is_discharge_votes, positive_is_charge_votes)
    confidence = round(100.0 * dominant / total, 1) if total else 0.0

    if total < max(int(minimum_evidence_samples), 1):
        state = "collecting"
        ready = False
        observed = None
    elif confidence < float(minimum_confidence_percent):
        state = "ambiguous"
        ready = False
        observed = None
    else:
        state = "proven"
        ready = True
        observed = positive_is_discharge_votes > positive_is_charge_votes

    return BatteryDirectionEvidence(
        state=state,
        ready=ready,
        positive_is_discharge=observed,
        evidence_samples=total,
        confidence_percent=confidence,
        positive_is_discharge_votes=positive_is_discharge_votes,
        positive_is_charge_votes=positive_is_charge_votes,
        basis_counts=tuple(sorted(basis_counts.items())),
        minimum_power_kw=float(minimum_power_kw),
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


def _diagnostic_source_age(value: Any) -> float | None:
    """Never let malformed optional age metadata affect commissioning."""
    if value is None or isinstance(value, bool):
        return None
    try:
        age = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(age, 1) if isfinite(age) and age >= 0.0 else None


def _self_use_register_settling_conflict(
    record: Any,
    *,
    ac_cross_check: dict[str, Any],
    residual_kw: float,
    tolerance_kw: float,
) -> bool:
    """Identify a narrow known-bad KH register cohort immediately after our write.

    These readings are NOT physical proof or control authority. A legitimate
    abnormal CT reading, older/missing timestamps or an unidentified write must
    still be counted as a failure. See 21 Oct 2026 commissioning issue #357.
    """
    probe = getattr(record, "foxess_balance_probe", None)
    timestamp = getattr(record, "timestamp", None)
    if (
        not isinstance(probe, dict)
        or not isinstance(timestamp, datetime)
        or timestamp.tzinfo is None
        or probe.get("last_applied_action") != "self_use"
        or probe.get("work_mode", {}).get("value") != "Self Use"
        or "command applied" not in str(probe.get("last_write_result", "")).lower()
        or ac_cross_check.get("status") != "ac_load_mismatch"
        or abs(residual_kw) <= tolerance_kw
        or abs(float(ac_cross_check.get("ac_load_residual_kw") or 0.0)) < 0.9
    ):
        return False
    raw_write_at = probe.get("last_write_at")
    if not isinstance(raw_write_at, str):
        return False
    try:
        write_at = datetime.fromisoformat(raw_write_at)
    except ValueError:
        return False
    if write_at.tzinfo is None:
        return False
    # The sample is written into HA around ten seconds after the first
    # Modbus cohort read at ~1 second after a mode write.
    age_after_write = (timestamp - write_at).total_seconds()
    if not 8.0 <= age_after_write <= 18.0:
        return False
    times = []
    for field in ("inverter_ac_output", "grid_ct", "inverter_reported_load"):
        entry = probe.get(field)
        if not isinstance(entry, dict):
            return False
        raw = entry.get("last_reported")
        if not isinstance(raw, str):
            return False
        try:
            reported = datetime.fromisoformat(raw)
        except ValueError:
            return False
        if reported.tzinfo is None:
            return False
        after_write = (reported - write_at).total_seconds()
        if not 0.3 <= after_write <= 2.5:
            return False
        times.append(reported)
    if (max(times) - min(times)).total_seconds() > 0.75:
        return False
    # Don't suppress a grid-limit violation or unexpected charging behaviour.
    export = getattr(record, "grid_export_kw", None)
    if export is None:
        return False
    try:
        export_kw = float(export)
    except (ValueError, TypeError):
        return False
    return bool(
        isfinite(export_kw)
        and 0.0 <= export_kw <= 7.0
        and float(ac_cross_check.get("inverter_ac_kw") or 0.0) >= 1.0
    )


def _released_backup_site_load_is_safe(
    record: Any, grid_import: float, house_load: float
) -> bool:
    """Recovery-only Back-up idle load proof; never permission to export.

    A house legitimately consuming ~2 kW can be supplied entirely by grid when
    KH is released to Back-up. The legacy 1.5 kW bound deadlocked commissioning
    even with balanced physical observations. Higher loads need extra EV and
    site-source proof, not a blanket wider idle threshold.
    """
    if not (0.0 <= grid_import <= 3.0 and 0.0 <= house_load <= 3.0):
        return False
    if grid_import <= 1.5 and house_load <= 1.5:
        return True
    # Above the legacy idle envelope the house must be consuming the import,
    # with no charging EV, solar surplus or unaccounted physical flow.
    try:
        ev_kw = float(record.ev_power_kw)
        ev_age = float(record.ev_power_age_seconds)
        solar_kw = float(record.solar_power_kw)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    return bool(
        record.ev_connected is False
        and record.ev_charging is False
        and all(isfinite(v) for v in (ev_kw, ev_age, solar_kw))
        and 0.0 <= ev_kw <= 0.05
        and 0.0 <= ev_age <= 30.0
        and 0.0 <= solar_kw <= 0.05
        and abs(grid_import - house_load) <= 0.25
    )


def _released_backup_distinct_readbacks(previous: Any, current: Any) -> bool:
    """Prove two recovery scans observed *new* CT, load and battery reports.

    Distinct coordinator timestamps alone cannot turn one cached Modbus cohort
    into two independent current physical observations (audit issue #361).
    """
    prior_probe = getattr(previous, "foxess_balance_probe", None)
    current_probe = getattr(current, "foxess_balance_probe", None)
    if not isinstance(prior_probe, dict) or not isinstance(current_probe, dict):
        return False

    def reported(probe: dict[str, Any], field: str) -> datetime | None:
        entry = probe.get(field)
        if not isinstance(entry, dict):
            return None
        raw = entry.get("last_reported")
        if not isinstance(raw, str):
            return None
        try:
            timestamp = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return timestamp if timestamp.tzinfo is not None else None

    for field in ("grid_ct", "inverter_reported_load"):
        earlier, later = reported(prior_probe, field), reported(current_probe, field)
        if earlier is None or later is None or (later - earlier).total_seconds() < 1.0:
            return False

    # Battery source is captured by the collector as a physical report age.
    # Reconstruct its reported time rather than accepting two coordinator polls.
    def battery_reported(record: Any) -> datetime | None:
        at = getattr(record, "timestamp", None)
        ages = getattr(record, "source_age_seconds", None)
        if (
            not isinstance(at, datetime)
            or at.tzinfo is None
            or not isinstance(ages, dict)
        ):
            return None
        try:
            age = float(ages["battery_power_kw"])
        except (KeyError, ValueError, TypeError, OverflowError):
            return None
        return at - timedelta(seconds=age) if isfinite(age) and age >= 0 else None

    first, last = battery_reported(previous), battery_reported(current)
    return bool(
        first is not None and last is not None and (last - first).total_seconds() >= 1.0
    )


def _released_backup_ct_recovery(
    record: Any, *, ac_cross_check: dict[str, Any]
) -> bool:
    """Narrow idle-only recovery when KH RPower stops reporting after release.

    This is not export proof: a future deliberate paid export must still pass
    the independent live guard and 2/2 staged battery/export checks.
    """
    probe = getattr(record, "foxess_balance_probe", None)
    at = getattr(record, "timestamp", None)
    if (
        not isinstance(probe, dict)
        or not isinstance(at, datetime)
        or at.tzinfo is None
        or ac_cross_check.get("status") != "not_time_aligned"
        or probe.get("last_write_result") != "KEMS FoxESS ownership released safely"
        or probe.get("last_applied_action") is not None
        or probe.get("commands_permitted_previous_cycle") is not False
        or not isinstance(probe.get("work_mode"), dict)
        or probe["work_mode"].get("value") != "Back-up"
        or probe["work_mode"].get("status") != "PASS"
        or getattr(record, "grid_flow_mode", None) != "separate_positive_sources"
    ):
        return False

    def reported_time(entry: Any) -> datetime | None:
        if not isinstance(entry, dict):
            return None
        value = entry.get("last_reported")
        if not isinstance(value, str):
            return None
        try:
            reported = datetime.fromisoformat(value)
        except ValueError:
            return None
        return reported if reported.tzinfo is not None else None

    try:
        release_at = datetime.fromisoformat(probe["last_write_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if release_at.tzinfo is None:
        return False
    elapsed = (at - release_at).total_seconds()
    if not 60.0 <= elapsed <= 7200.0:
        return False

    ac = probe.get("inverter_ac_output")
    ct = probe.get("grid_ct")
    house_probe = probe.get("inverter_reported_load")
    ac_at = reported_time(ac)
    ct_at = reported_time(ct)
    house_at = reported_time(house_probe)
    if any(value is None for value in (ac_at, ct_at, house_at)):
        return False
    # RPower zero after KEMS gave up ownership is allowed to become old.
    # Fresh non-zero or contradictory AC must never take this fallback.
    if not (
        0.0 <= (ac_at - release_at).total_seconds() <= 180.0
        and (at - ac_at).total_seconds() >= 90.0
        and 0.0 <= (at - ct_at).total_seconds() <= 90.0
        and 0.0 <= (at - house_at).total_seconds() <= 45.0
    ):
        return False
    try:
        ac_kw = float(ac["value"])
        ct_kw = float(ct["value"])
        reported_house_kw = float(house_probe["value"])
        actual_house = float(record.house_load_kw)
        battery = float(record.battery_power_kw)
        grid_import = float(record.grid_import_kw)
        grid_export = float(record.grid_export_kw)
        raw_import = float(record.raw_grid_import_kw)
        raw_export = float(record.raw_grid_export_kw)
        battery_age = float(record.source_age_seconds["battery_power_kw"])
        load_age = float(record.source_age_seconds["house_load_kw"])
    except (KeyError, AttributeError, TypeError, ValueError):
        return False
    if not all(
        isfinite(value)
        for value in (
            ac_kw,
            ct_kw,
            reported_house_kw,
            actual_house,
            battery,
            grid_import,
            grid_export,
            raw_import,
            raw_export,
            battery_age,
            load_age,
        )
    ):
        return False
    return bool(
        abs(ac_kw) <= 0.10
        and abs(ct_kw + grid_import - grid_export) <= 0.10
        and abs(raw_import - grid_import) <= 0.05
        and abs(raw_export - grid_export) <= 0.05
        and abs(reported_house_kw - actual_house) <= 0.10
        and 0.0 <= grid_export <= 0.10
        and _released_backup_site_load_is_safe(record, grid_import, actual_house)
        and abs(battery) <= 0.6
        and 0.0 <= battery_age <= 45.0
        and 0.0 <= load_age <= 45.0
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
    quarantine_self_use_settling: bool = False,
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
    failed_samples: list[dict[str, Any]] = []
    ac_statuses: Counter[str] = Counter()
    transition_statuses: Counter[str] = Counter()
    transition_examples: list[dict[str, Any]] = []
    previous_eligible: Any = None
    settling_quarantined: list[dict[str, Any]] = []
    settled_current_samples: dict[int, bool] = {}
    safe_release_samples: dict[int, Any] = {}
    safe_release_idle_proof_count = 0
    balanced = 0
    invalid = 0
    observed_export_limit_violations = 0
    required = set(
        FOXESS_REQUIRED_TELEMETRY_FIELDS
        if battery_required
        else FOXESS_SITE_TELEMETRY_FIELDS
    )

    for record_index, record in enumerate(recent):
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
        if quarantine_self_use_settling and grid_export > 7.0:
            # A real 7 kW DNO limit violation must block commissioning even
            # when the statistical balance happens to match.
            observed_export_limit_violations += 1
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
        # AC readings are correlated read-only for EVERY eligible sample, not
        # only failing DC/AC mixed-boundary samples. Never promote them to proof.
        ac_cross_check = assess_foxess_ac_side_sample(record)
        ac_statuses[str(ac_cross_check["status"])] += 1
        ac_transition = (
            assess_foxess_ac_ct_transition(previous_eligible, record)
            if previous_eligible is not None
            else None
        )
        previous_eligible = record
        settling = bool(
            quarantine_self_use_settling
            and _self_use_register_settling_conflict(
                record,
                ac_cross_check=ac_cross_check,
                residual_kw=residual,
                tolerance_kw=tolerance,
            )
        )
        if settling:
            settling_quarantined.append(
                {
                    "timestamp": record.timestamp.isoformat(),
                    "residual_kw": round(residual, 3),
                    "last_write_at": record.foxess_balance_probe["last_write_at"],
                    "reason": "Self Use command transitional KH register cohort",
                }
            )
        else:
            residuals.append(residual)
        # A KH in Back-up after a verified safe ownership release can stop
        # updating RPower. Require fresh split-grid CT, house and battery
        # measurements instead; *never* accept a live AC disagreement.
        idle_release_verified = bool(
            quarantine_self_use_settling
            and not settling
            and abs(residual) <= tolerance
            and _released_backup_ct_recovery(record, ac_cross_check=ac_cross_check)
        )
        if idle_release_verified:
            safe_release_idle_proof_count += 1
            safe_release_samples[record_index] = record
        settled_current_samples[record_index] = (
            not settling
            and abs(residual) <= tolerance
            and (
                ac_cross_check.get("status") == "ac_cross_check_pass"
                or idle_release_verified
            )
        )
        if ac_transition is not None:
            transition_statuses[str(ac_transition["status"])] += 1
            if (
                ac_transition["status"]
                == "ct_export_step_without_matching_source_or_load_step"
            ):
                current_time = getattr(record, "timestamp", None)
                transition_examples.append(
                    {
                        "timestamp": (
                            current_time.isoformat()
                            if hasattr(current_time, "isoformat")
                            else None
                        ),
                        **ac_transition,
                    }
                )
                if len(transition_examples) > 8:
                    del transition_examples[:-8]
        if settling:
            # Never treat command-transition register disagreement as a pass.
            # Exclusion applies only to rolling statistical readiness, not
            # present-tense grid direction, power cap or stage export proof.
            continue
        if abs(residual) <= tolerance:
            balanced += 1
        else:
            timestamp = getattr(record, "timestamp", None)
            ages = getattr(record, "source_age_seconds", None)
            source_ages = ages if isinstance(ages, dict) else {}
            power_fields = (
                "solar_power_kw",
                "battery_power_kw",
                "house_load_kw",
                "grid_import_kw",
                "grid_export_kw",
            )
            failed_samples.append(
                {
                    "timestamp": (
                        timestamp.isoformat()
                        if hasattr(timestamp, "isoformat")
                        else None
                    ),
                    "power_kw": {name: round(values[name], 3) for name in power_fields},
                    "source_ages_seconds": {
                        name: _diagnostic_source_age(source_ages.get(name))
                        for name in power_fields
                    },
                    "residual_kw": round(residual, 3),
                    "tolerance_kw": round(tolerance, 3),
                    # Read-only mode/write context captured in the same
                    # coordinator cycle, never evidence for control authority.
                    "foxess_mode_probe": dict(
                        getattr(record, "foxess_balance_probe", None) or {}
                    ),
                    "foxess_ac_cross_check": ac_cross_check,
                    "foxess_ac_transition": ac_transition,
                }
            )
            if len(failed_samples) > 8:
                del failed_samples[:-8]

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

    # Fail closed while a real mode change is still settling, or if too
    # many scores depend on excluding a source KEMS cannot independently meter.
    # A clean session needs the original minimum_samples observations.
    # The more demanding 30-sample/two-latest-AC-readback rule applies ONLY
    # when a transition has actually been excluded from the rolling score.
    # Applying it on every fresh restart wrongly blocked commissioning at
    # 14/14 genuinely balanced samples with zero quarantined transitions.
    last_index = len(recent) - 1
    backup_pair_distinct = (
        last_index in safe_release_samples
        and last_index - 1 in safe_release_samples
        and _released_backup_distinct_readbacks(
            safe_release_samples[last_index - 1], safe_release_samples[last_index]
        )
    )
    # Ordinary independent fresh AC cross-checks retain their original rule.
    # If either latest sample relies on frozen-AC Back-up recovery, require
    # both latest samples to be safe-released AND physically distinct.
    latest_pair_verified = (
        settled_current_samples.get(last_index, False)
        and settled_current_samples.get(last_index - 1, False)
        and (
            (
                last_index not in safe_release_samples
                and last_index - 1 not in safe_release_samples
            )
            or backup_pair_distinct
        )
    )
    settling_verified = (
        not quarantine_self_use_settling
        or not settling_quarantined
        or (
            len(settling_quarantined) <= 8
            and eligible >= max(minimum_samples, 30)
            and len(recent) >= 2
            and latest_pair_verified
        )
    )
    if len(recent) < minimum_samples:
        state = "collecting"
        ready = False
    elif eligible < minimum_samples:
        state = "incomplete"
        ready = False
    elif observed_export_limit_violations:
        state = "grid_export_limit_violation"
        ready = False
    elif not settling_verified:
        state = "settling_unverified"
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
        failed_samples=tuple(failed_samples),
        ac_side_audit={
            "informational_only": True,
            "independent_load_proven": False,
            "hardware_write_authorised": False,
            "eligible_samples": eligible,
            "post_command_settling_quarantined_count": len(settling_quarantined),
            "post_command_settling_examples": settling_quarantined[-8:],
            "post_command_settling_verified": settling_verified,
            "post_safe_release_idle_proofs": safe_release_idle_proof_count,
            "post_safe_release_latest_pair_distinct": backup_pair_distinct,
            "observed_grid_export_limit_violations": observed_export_limit_violations,
            "status_counts": dict(sorted(ac_statuses.items())),
            "transition_status_counts": dict(sorted(transition_statuses.items())),
            "ct_export_step_examples": transition_examples,
            "caveat": (
                "KH Load Power, RPower and Grid CT are distinct Modbus registers "
                "but may be computed or filtered by FoxESS firmware; CT steps "
                "do not prove the CT clamp or house meter is physically faulty"
            ),
        },
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
