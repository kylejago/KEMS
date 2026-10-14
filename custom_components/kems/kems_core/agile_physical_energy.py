"""Conservative live physical-energy evidence for paid Agile export only.

This ledger is *not* the Agile simulation SOC. It only starts from a real
FoxESS SOC report that was recently observed by the already-validated provider.
Newer SOC reports re-anchor it; older unchanged SOC cannot raise its estimate.
An absent observation is debited at the *full* feasible discharge rate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

from .models import ControlConfig, SimulationConfig, Snapshot

_MAX_SEED_SOC_AGE_SECONDS = 3600.0
_MAX_NORMAL_INTERVAL_SECONDS = 120.0
_MAX_CONTINUITY_GAP_SECONDS = 900.0
_MAX_REPLAY_LOOKBACK_HOURS = 12.0
_MAX_POWER_SOURCE_AGE_SECONDS = 90.0
_SAMPLED_POWER_MARGIN_KW = 1.0
_MIN_WORST_DISCHARGE_KW = 10.0


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) else None


@dataclass(frozen=True, slots=True)
class PhysicalEnergyEvidence:
    """Audit-friendly energy estimate for one exactly-matched control scan."""

    observed_at: datetime
    lower_bound_kwh: float | None
    status: str
    source_soc_at: datetime | None
    source_soc_percent: float | None
    samples: int
    pessimistic_discharge_kwh: float
    worst_case_gap_kwh: float
    direct_power_age_seconds: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "observed_at": self.observed_at.isoformat(),
            "physical_energy_lower_bound_kwh": (
                round(self.lower_bound_kwh, 3)
                if self.lower_bound_kwh is not None
                else None
            ),
            "source_soc_at": (
                self.source_soc_at.isoformat()
                if self.source_soc_at is not None
                else None
            ),
            "source_soc_percent": self.source_soc_percent,
            "samples": self.samples,
            "total_pessimistic_discharge_kwh": round(self.pessimistic_discharge_kwh, 3),
            "worst_case_gap_kwh": round(self.worst_case_gap_kwh, 3),
            "direct_power_age_seconds": self.direct_power_age_seconds,
            "scope": "paid_agile_physical_reserve_only",
            "charging_credit_kwh": 0.0,
        }


class PaidAgilePhysicalEnergyTracker:
    """Maintain a pessimistic battery-energy floor from actual FoxESS telemetry.

    Short, verified power-sample intervals use the larger endpoint discharge
    plus a continuous 1 kW uncertainty allowance. Missing, stale or >120 sec
    intervals consume the *full* configured worst-case discharge budget.
    No power or solar reading is ever used to increase energy. Hardware MinSOC
    remains the independent mandatory backstop during Force Discharge.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Discard provenance, including across coordinator restart."""
        self._last_at: datetime | None = None
        self._soc_at: datetime | None = None
        self._soc_percent: float | None = None
        self._energy_kwh: float | None = None
        self._previous_discharge_kw: float | None = None
        self._samples = 0
        self._total_debit_kwh = 0.0
        self._gap_debit_kwh = 0.0
        self._status = "waiting_for_verified_physical_soc"

    def _result(
        self,
        now: datetime,
        power_age: float | None,
        *,
        usable: bool,
    ) -> PhysicalEnergyEvidence:
        return PhysicalEnergyEvidence(
            observed_at=now,
            lower_bound_kwh=(
                self._energy_kwh if usable and self._samples >= 2 else None
            ),
            status=self._status,
            source_soc_at=self._soc_at,
            source_soc_percent=self._soc_percent,
            samples=self._samples,
            pessimistic_discharge_kwh=self._total_debit_kwh,
            worst_case_gap_kwh=self._gap_debit_kwh,
            direct_power_age_seconds=power_age,
        )

    def observe(
        self,
        snapshot: Snapshot,
        simulation: SimulationConfig,
        control: ControlConfig,
        *,
        now: datetime,
    ) -> PhysicalEnergyEvidence:
        """Consume exactly one chronological physical scan, never simulation SOC."""
        cap = _number(simulation.battery_capacity_kwh)
        efficiency = _number(simulation.discharge_efficiency)
        worst_kw = max(
            _MIN_WORST_DISCHARGE_KW,
            _number(simulation.max_discharge_kw) or 0.0,
            _number(control.max_discharge_kw) or 0.0,
            _number(control.inverter_limit_kw) or 0.0,
        )
        power_age = _number(snapshot.source_age_seconds.get("battery_power_kw"))
        soc_age = _number(snapshot.source_age_seconds.get("battery_soc"))
        soc = _number(snapshot.battery_soc)
        overall_age = _number(snapshot.source_data_age_seconds)
        valid_shape = (
            now.tzinfo is not None
            and snapshot.timestamp.tzinfo is not None
            and abs((now - snapshot.timestamp).total_seconds()) <= 120.0
            and cap is not None
            and cap > 0.0
            and efficiency is not None
            and 0.0 < efficiency <= 1.0
            and soc is not None
            and 0.0 <= soc <= 100.0
            and soc_age is not None
            and soc_age >= 0.0
            and "battery_soc" not in snapshot.stale_fields
            and overall_age is not None
            and 0.0 <= overall_age <= control.stale_data_seconds
        )
        if not valid_shape:
            self.reset()
            self._status = "missing_or_unverified_physical_soc_or_device"
            return self._result(now, power_age, usable=False)
        assert cap is not None and efficiency is not None
        assert soc is not None and soc_age is not None

        signed = _number(snapshot.battery_power_kw)
        fresh_power = (
            signed is not None
            and power_age is not None
            and 0.0
            <= power_age
            <= min(
                _MAX_POWER_SOURCE_AGE_SECONDS,
                control.stale_data_seconds,
            )
            and "battery_power_kw" not in snapshot.stale_fields
        )
        discharge_kw = (
            max(
                signed if simulation.battery_power_positive_is_discharge else -signed,
                0.0,
            )
            if fresh_power and signed is not None
            else None
        )
        soc_sample_at = snapshot.timestamp - timedelta(seconds=soc_age)

        # Never seed from a SOC that is already more than an hour old.
        # This is a deliberate cold-start protection, not a timer reset.
        if self._last_at is None:
            if soc_age > _MAX_SEED_SOC_AGE_SECONDS:
                self._status = "awaiting_recent_physical_soc_anchor"
                return self._result(now, power_age, usable=False)
            seed_debit = worst_kw * soc_age / (3600.0 * efficiency)
            self._soc_at = soc_sample_at
            self._soc_percent = soc
            self._energy_kwh = max(cap * soc / 100.0 - seed_debit, 0.0)
            self._last_at = now
            self._previous_discharge_kw = discharge_kw
            self._samples = 1
            self._total_debit_kwh = seed_debit
            self._gap_debit_kwh = seed_debit
            self._status = (
                "anchor_seeded_waiting_second_sample"
                if fresh_power
                else "anchor_seeded_waiting_fresh_power"
            )
            return self._result(now, power_age, usable=False)

        assert self._last_at is not None
        assert self._soc_at is not None and self._soc_percent is not None
        assert self._energy_kwh is not None
        elapsed = (now - self._last_at).total_seconds()
        if elapsed <= 0.0 or elapsed > _MAX_CONTINUITY_GAP_SECONDS:
            self.reset()
            self._status = "physical_observation_timeline_interrupted"
            # A following scan may seed again if it has a recent SOC.
            return self._result(now, power_age, usable=False)

        if soc_sample_at > self._soc_at + timedelta(seconds=2):
            # Only an actually *newer physical SOC report* may add energy.
            # A fresh report supersedes the ledger's older low estimate.
            seed_debit = worst_kw * soc_age / (3600.0 * efficiency)
            self._soc_at = soc_sample_at
            self._soc_percent = soc
            self._energy_kwh = max(cap * soc / 100.0 - seed_debit, 0.0)
            self._last_at = now
            self._previous_discharge_kw = discharge_kw
            self._samples += 1
            self._total_debit_kwh = seed_debit
            self._gap_debit_kwh = seed_debit
            self._status = (
                "new_verified_soc_anchor"
                if fresh_power
                else "new_soc_anchor_power_unavailable"
            )
            return self._result(now, power_age, usable=fresh_power)

        if (
            soc_sample_at < self._soc_at - timedelta(seconds=2)
            or abs(soc - self._soc_percent) > 0.01
        ):
            self.reset()
            self._status = "soc_source_timestamp_or_value_conflict"
            return self._result(now, power_age, usable=False)

        if (
            elapsed > _MAX_NORMAL_INTERVAL_SECONDS
            or discharge_kw is None
            or self._previous_discharge_kw is None
        ):
            # Unobserved power cannot be inferred from a quiet endpoint.
            debit = worst_kw * elapsed / (3600.0 * efficiency)
            self._gap_debit_kwh += debit
            current_usable = False
            self._status = "worst_case_unobserved_discharge_debited"
        else:
            discharge_upper_kw = (
                max(discharge_kw, self._previous_discharge_kw) * 1.10
                + _SAMPLED_POWER_MARGIN_KW
            )
            debit = discharge_upper_kw * elapsed / (3600.0 * efficiency)
            current_usable = True
            self._status = "verified_power_continuity_with_margin"

        self._energy_kwh = max(self._energy_kwh - debit, 0.0)
        self._total_debit_kwh += debit
        self._last_at = now
        self._previous_discharge_kw = discharge_kw
        self._samples += 1
        if not fresh_power:
            self._status = "power_unavailable_no_export"
            current_usable = False
        return self._result(now, power_age, usable=current_usable)

    def replay(
        self,
        records: Iterable[Snapshot],
        simulation: SimulationConfig,
        control: ControlConfig,
        *,
        now: datetime,
    ) -> None:
        """Rebuild evidence from recorded physical scans; never trust saved totals.

        History is sampled every five minutes, so each historical gap is debited
        at the *full* 10 kW-or-higher physical discharge rate. This deliberately
        costs more energy headroom than continuous live telemetry and never
        upgrades old power data into evidence of continuous zero discharge.
        """
        self.reset()
        if now.tzinfo is None:
            return
        start = now - timedelta(hours=_MAX_REPLAY_LOOKBACK_HOURS)
        recent = sorted(
            (
                item
                for item in records
                if item.timestamp.tzinfo is not None and start <= item.timestamp <= now
            ),
            key=lambda item: item.timestamp,
        )
        for item in recent:
            self.observe(item, simulation, control, now=item.timestamp)
