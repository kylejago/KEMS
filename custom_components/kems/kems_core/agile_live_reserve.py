"""Physical SOC and remaining-house budget veto for paid Agile export.

The rolling Agile plan is a simulation, NOT evidence that its projected SOC
is available in the actual KH7 battery. Only constrain deliberate physical
export; never alter the accounting, history or no-paid-export control path.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from math import isfinite
from typing import Any

from .agile_physical_energy import PhysicalEnergyEvidence
from .models import ControlConfig, ControlState, SimulationConfig, Snapshot

_MIN_PLANNING_RESERVE_PERCENT = 15.0
_MIN_HOUSE_BUFFER_KWH = 2.0
_HOUSE_BUFFER_FRACTION = 0.20
_EXPORT_PROOF_HORIZON_HOURS = 0.5
_MAX_FORECAST_SOLAR_CREDIT_FRACTION = 0.25
_SOLAR_CREDIT_MIN_CONFIDENCE = 80.0
# FoxESS may report an unchanged integer SOC less frequently than power/CT.
# Accept unchanged physical SOC for at most one hour, but pessimistically
# debit the full elapsed time at worst-case battery discharge before any export.
# This window requires live same-device FoxESS Modbus cohort evidence; the
# provider validates device identity and excludes unverified/stale readings.
# A missing cohort or expired window always fails closed.
_MAX_COHORT_SOC_AGE_SECONDS = 3600.0
_MIN_CONSERVATIVE_DISCHARGE_KW = 10.0
# Grace applies only to a *previously verified unplugged* EV with live zero
# charging power. Never carry this across restart or a positive EV observation.
_AGILE_EV_UNPLUGGED_GRACE_SECONDS = 90.0
_AGILE_EV_MAX_POWER_REPORT_AGE_SECONDS = 180.0
# Plugged-in EVs may start charging without another status transition. A
# zero-power sample from a cloud charger must be very recent before export.
_AGILE_EV_CONNECTED_IDLE_POWER_AGE_SECONDS = 30.0
_AGILE_EV_IDLE_POWER_KW = 0.1

_COHORT_POWER_FIELDS = (
    "battery_power_kw",
    "house_load_kw",
    "solar_power_kw",
    "grid_import_kw",
    "grid_export_kw",
)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if isfinite(number) else None


def physical_energy_evidence_matches_snapshot(
    evidence: PhysicalEnergyEvidence | None,
    snapshot: Snapshot,
    control_config: ControlConfig,
    *,
    now: datetime,
) -> bool:
    """Require the exact same fresh FoxESS physical ledger proof for plan and guard.

    An old coordinator cycle, a changed SOC report, an invalid physical source,
    or stale device power can never re-authorise live battery export.
    """
    physical_age = _finite(
        snapshot.source_age_seconds.get("battery_soc")
        if isinstance(snapshot.source_age_seconds, dict)
        else None
    )
    observed = _finite(snapshot.battery_soc)
    physical_power_age = _finite(
        snapshot.source_age_seconds.get("battery_power_kw")
        if isinstance(snapshot.source_age_seconds, dict)
        else None
    )
    overall_age = _finite(snapshot.source_data_age_seconds)
    if (
        observed is None
        or not 0.0 <= observed <= 100.0
        or "battery_soc" in snapshot.stale_fields
        or overall_age is None
        or not 0.0 <= overall_age <= control_config.stale_data_seconds
    ):
        return False
    return bool(
        evidence is not None
        and evidence.lower_bound_kwh is not None
        and evidence.source_soc_at is not None
        and evidence.source_soc_percent is not None
        and evidence.samples >= 2
        and physical_age is not None
        and physical_age >= 0.0
        and observed is not None
        and abs(evidence.source_soc_percent - observed) < 0.01
        and snapshot.timestamp.tzinfo is not None
        and now.tzinfo is not None
        and abs(
            (
                evidence.source_soc_at
                - (snapshot.timestamp - timedelta(seconds=physical_age))
            ).total_seconds()
        )
        <= 2.0
        and 0.0 <= (now - evidence.observed_at).total_seconds() <= 2.0
        and physical_power_age is not None
        and 0.0 <= physical_power_age <= min(control_config.stale_data_seconds, 90)
        and "battery_power_kw" not in snapshot.stale_fields
        and _finite(snapshot.battery_power_kw) is not None
    )



# Cloud Ohme periodically reports unavailable for ~40 seconds. This is an
# explicitly bounded, session-only concession for an *already verified idle*
# connected EV. It is not electrical isolation: the EV could start during an
# outage before cloud telemetry resumes. An independently metered EV circuit
# is required for hard battery-to-EV protection.
_AGILE_CONNECTED_IDLE_GRACE_SECONDS = 60.0
_AGILE_CONNECTED_IDLE_LAST_PROOF_SECONDS = 90.0
_AGILE_CONNECTED_IDLE_LOAD_AGE_SECONDS = 35.0
_AGILE_CONNECTED_IDLE_LOAD_STEP_KW = 1.0
_AGILE_CONNECTED_IDLE_GRID_IMPORT_VETO_KW = 0.3


class PaidAgileConnectedIdleContinuity:
    """Non-persistent, single-outage EV idle proof for paid Agile only.

    A lost Ohme report cannot refresh its own grace. All positive charging
    indications, a large site-load step, or absent/stale Modbus load telemetry
    invalidate the proof for the remainder of this outage.
    """

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self._last_idle_at: datetime | None = None
        self._idle_house_load_kw: float | None = None
        self._outage_started_at: datetime | None = None

    @staticmethod
    def _live_house_load(snapshot: Snapshot) -> float | None:
        power = _finite(snapshot.house_load_kw)
        age = _finite(snapshot.source_age_seconds.get("house_load_kw"))
        if (
            power is None
            or power < 0.0
            or age is None
            or not 0.0 <= age <= _AGILE_CONNECTED_IDLE_LOAD_AGE_SECONDS
            or "house_load_kw" in snapshot.stale_fields
        ):
            return None
        return power

    def _continuity_valid(self, snapshot: Snapshot, *, now: datetime) -> bool:
        if (
            self._last_idle_at is None
            or self._idle_house_load_kw is None
            or self._outage_started_at is None
            or now.tzinfo is None
            or self._last_idle_at.tzinfo is None
            or self._outage_started_at.tzinfo is None
            or snapshot.ev_connected is False
            or snapshot.ev_charging is True
        ):
            return False
        ev_power = _finite(snapshot.ev_power_kw)
        if ev_power is not None and (ev_power < 0.0 or ev_power > _AGILE_EV_IDLE_POWER_KW):
            return False
        if not (
            timedelta(0)
            <= now - self._outage_started_at
            <= timedelta(seconds=_AGILE_CONNECTED_IDLE_GRACE_SECONDS)
            and timedelta(0)
            <= self._outage_started_at - self._last_idle_at
            <= timedelta(seconds=_AGILE_CONNECTED_IDLE_LAST_PROOF_SECONDS)
        ):
            return False
        house = self._live_house_load(snapshot)
        if house is None or house > (
            self._idle_house_load_kw + _AGILE_CONNECTED_IDLE_LOAD_STEP_KW
        ):
            return False
        grid_import = _finite(snapshot.grid_import_kw)
        grid_age = _finite(snapshot.source_age_seconds.get("grid_import_kw"))
        if (
            grid_import is not None
            and grid_import > _AGILE_CONNECTED_IDLE_GRID_IMPORT_VETO_KW
            and grid_age is not None
            and 0.0 <= grid_age <= _AGILE_CONNECTED_IDLE_LOAD_AGE_SECONDS
            and "grid_import_kw" not in snapshot.stale_fields
        ):
            return False
        return True

    def permits(self, snapshot: Snapshot, *, now: datetime) -> bool:
        """Independent final-guard check; evidence string alone is insufficient."""
        return self._continuity_valid(snapshot, now=now)

    def assess(self, snapshot: Snapshot, *, now: datetime) -> bool:
        """Return a bounded temporary allowance or learn a fresh idle baseline."""
        ev_power = _finite(snapshot.ev_power_kw)
        if (
            snapshot.ev_connected is False
            or snapshot.ev_charging is True
            or (ev_power is not None and (ev_power < 0.0 or ev_power > _AGILE_EV_IDLE_POWER_KW))
        ):
            self.clear()
            return False

        power_age = _finite(snapshot.ev_power_age_seconds)
        house = self._live_house_load(snapshot)
        if (
            snapshot.ev_connected is True
            and snapshot.ev_charging is False
            and ev_power is not None
            and 0.0 <= ev_power <= _AGILE_EV_IDLE_POWER_KW
            and power_age is not None
            and 0.0 <= power_age <= _AGILE_EV_CONNECTED_IDLE_POWER_AGE_SECONDS
            and "ev_power_kw" not in snapshot.stale_fields
        ):
            # Fresh confirmed idle is the sole way to re-arm this grace.
            self._last_idle_at = now if house is not None else None
            self._idle_house_load_kw = house
            self._outage_started_at = None
            return False

        if self._last_idle_at is None or self._idle_house_load_kw is None:
            return False
        if self._outage_started_at is None:
            self._outage_started_at = now
        if not self._continuity_valid(snapshot, now=now):
            self.clear()
            return False
        return True


def assess_paid_agile_ev_continuity(
    snapshot: Snapshot,
    *,
    now: datetime,
    last_confirmed_unplugged_at: datetime | None,
) -> tuple[bool, datetime | None, str]:
    """Permit paid export when Ohme is verifiably idle, even if plugged in.

    Positive charging or EV draw always veto export. Connected-idle is allowed
    only with an explicit NOT charging state and a particularly fresh zero-power
    sample. Unknown connections retain the older bounded *unplugged-only*
    grace: connected-idle evidence never creates a grace anchor. This cannot
    provide hard electrical isolation of a shared home/EV bus.
    """
    connected = snapshot.ev_connected
    charging = snapshot.ev_charging
    power_kw = _finite(snapshot.ev_power_kw)
    power_age = _finite(snapshot.ev_power_age_seconds)
    if charging is True or (
        power_kw is not None and power_kw > _AGILE_EV_IDLE_POWER_KW
    ):
        return False, None, "EV charging or measured EV power observed"

    zero_power_fresh = bool(
        power_kw is not None
        and 0.0 <= power_kw <= _AGILE_EV_IDLE_POWER_KW
        and power_age is not None
        and 0.0 <= power_age <= _AGILE_EV_MAX_POWER_REPORT_AGE_SECONDS
        and "ev_power_kw" not in snapshot.stale_fields
    )
    if not zero_power_fresh:
        return False, None, "EV zero-power observation missing/stale"

    if connected is True:
        # An attached car must have a *definitely stopped* charger and an
        # especially fresh zero-power reading. A plugged-in vehicle can start
        # charging without changing its physical connection status. Clear any
        # previous unplugged grace, so an Ohme outage fails closed afterward.
        if charging is not False:
            return False, None, "EV connected; charging state not confirmed idle"
        if power_age is None or power_age > _AGILE_EV_CONNECTED_IDLE_POWER_AGE_SECONDS:
            return False, None, "EV connected; zero-power sample too old"
        return True, None, "confirmed_connected_idle_zero_power"

    if connected is False:
        # Confirmed unplugged is stronger than a transient unavailable
        # charging flag; refresh the brief grace anchor from the live status.
        return (
            True,
            now,
            (
                "confirmed_unplugged"
                if charging is False
                else "unplugged_with_fresh_zero_ev_power"
            ),
        )

    if (
        last_confirmed_unplugged_at is not None
        and now.tzinfo is not None
        and last_confirmed_unplugged_at.tzinfo is not None
        and timedelta(0)
        <= now - last_confirmed_unplugged_at
        <= timedelta(seconds=_AGILE_EV_UNPLUGGED_GRACE_SECONDS)
    ):
        return True, last_confirmed_unplugged_at, "bounded_unplugged_source_grace"

    return False, None, "EV connection uncertain without recent unplugged proof"


def guard_paid_agile_physical_export(
    control: ControlState,
    snapshot: Snapshot,
    forecast_plan: Any,
    simulation_config: SimulationConfig,
    control_config: ControlConfig,
    *,
    now: datetime,
    ev_export_safe: bool | None = None,
    ev_export_evidence: str = "no verified disconnected EV evidence",
    physical_energy_evidence: PhysicalEnergyEvidence | None = None,
    connected_idle_continuity: PaidAgileConnectedIdleContinuity | None = None,
) -> tuple[ControlState, dict[str, Any]]:
    """Cap deliberate export by *measured* SOC minus future house reserve.

    Refuse deliberate export if any input needed for the reserve is missing,
    stale, contradictory or untrusted. This does not block normal Self Use
    discharge to the house, and does not alter confirmed-cheap Force Charge.
    """
    request = max(_finite(control.desired_battery_export_power_kw) or 0.0, 0.0)
    report: dict[str, Any] = {
        "requested_export_kw": round(request, 3),
        "permitted_export_kw": 0.0,
        "physical_soc_percent": _finite(snapshot.battery_soc),
        "status": "not_applicable",
        "basis": "physical FoxESS SOC + forecast house demand; simulated SOC excluded",
        "ev_export_evidence": ev_export_evidence,
        "physical_energy_evidence": (
            physical_energy_evidence.as_dict()
            if physical_energy_evidence is not None
            else None
        ),
    }
    if snapshot.cheap_period_confirmed or snapshot.saving_session_active:
        report["status"] = "higher_priority_cheap_or_event"
        return control, report
    if request <= 0.001:
        report["status"] = "no_deliberate_export_requested"
        return control, report

    def reduce(
        reason: str, limit_kw: float = 0.0
    ) -> tuple[ControlState, dict[str, Any]]:
        allowed = round(min(max(limit_kw, 0.0), request), 3)
        report.update(
            {
                "status": "blocked" if allowed <= 0.001 else "capped",
                "reason": reason,
                "permitted_export_kw": allowed,
            }
        )
        if allowed <= 0.001:
            return (
                replace(
                    control,
                    desired_work_mode="Self Use",
                    desired_battery_export_power_kw=0.0,
                    desired_total_discharge_power_kw=max(
                        control.desired_battery_to_home_power_kw, 0.0
                    ),
                    next_action="Agile physical house reserve: " + reason,
                ),
                report,
            )
        return (
            replace(
                control,
                desired_battery_export_power_kw=allowed,
                desired_total_discharge_power_kw=round(
                    max(control.desired_battery_to_home_power_kw, 0.0) + allowed, 3
                ),
                next_action="Agile physical export capped by house reserve: " + reason,
            ),
            report,
        )

    # An explicit connected-idle grace is valid only if the session's physical
    # evidence still passes at this exact final command guard. Generic safe=True
    # and a copied evidence string never grant export on their own.
    connected_idle_grace_proven = bool(
        ev_export_safe is True
        and ev_export_evidence == "bounded_connected_idle_source_grace"
        and connected_idle_continuity is not None
        and connected_idle_continuity.permits(snapshot, now=now)
    )
    # Direct live zero Ohme power remains mandatory outside the bounded bridge.
    if ev_export_safe is not None and not connected_idle_grace_proven:
        ev_power = _finite(snapshot.ev_power_kw)
        ev_age = _finite(snapshot.ev_power_age_seconds)
        if (
            ev_power is None
            or not 0.0 <= ev_power <= _AGILE_EV_IDLE_POWER_KW
            or ev_age is None
            or not 0.0 <= ev_age <= _AGILE_EV_MAX_POWER_REPORT_AGE_SECONDS
            or "ev_power_kw" in snapshot.stale_fields
        ):
            return reduce("EV zero-power observation missing/stale")

    # A connected-idle EV is eligible only with a matching *current-scan*
    # assessment and a strictly newer direct zero-power report. A caller
    # supplying a generic True cannot bypass the connection veto.
    connected_idle_proven = bool(
        ev_export_safe is True
        and ev_export_evidence == "confirmed_connected_idle_zero_power"
        and snapshot.ev_connected is True
        and snapshot.ev_charging is False
        and (direct_ev_power := _finite(snapshot.ev_power_kw)) is not None
        and 0.0 <= direct_ev_power <= _AGILE_EV_IDLE_POWER_KW
        and (direct_ev_age := _finite(snapshot.ev_power_age_seconds)) is not None
        and 0.0 <= direct_ev_age <= _AGILE_EV_CONNECTED_IDLE_POWER_AGE_SECONDS
        and "ev_power_kw" not in snapshot.stale_fields
    )
    # Previously verified *unplugged* grace may bridge missing Ohme status,
    # but any live positive charging or power signal always vetoes export.
    if (
        not (
            ev_export_safe
            if ev_export_safe is not None
            else snapshot.ev_connected is False and snapshot.ev_charging is False
        )
        or (
            snapshot.ev_connected is True
            and not (connected_idle_proven or connected_idle_grace_proven)
        )
        or snapshot.ev_charging is True
        or (
            (live_ev_power := _finite(snapshot.ev_power_kw)) is not None
            and live_ev_power > _AGILE_EV_IDLE_POWER_KW
        )
    ):
        return reduce("EV connected/uncertain; protect shared-bus battery")
    age = _finite(snapshot.source_data_age_seconds)
    # Overall dynamic freshness can be healthy while the SOC field is old.
    # Physical export must use the SOC field's own observed age.
    physical_age = _finite(
        snapshot.source_age_seconds.get("battery_soc")
        if isinstance(snapshot.source_age_seconds, dict)
        else None
    )
    observed = _finite(snapshot.battery_soc)
    energy_proven = physical_energy_evidence_matches_snapshot(
        physical_energy_evidence,
        snapshot,
        control_config,
        now=now,
    )
    if (
        observed is None
        or not 0.0 <= observed <= 100.0
        or "battery_soc" in snapshot.stale_fields
        or age is None
        or age < 0.0
        or age > control_config.stale_data_seconds
        or physical_age is None
        or physical_age < 0.0
        or (physical_age > _MAX_COHORT_SOC_AGE_SECONDS and not energy_proven)
    ):
        return reduce("physical battery SOC missing, stale or too old to bound")

    if physical_age > control_config.stale_data_seconds:
        # The raw SOC age alone cannot justify export. Require a *current*
        # independent FoxESS Modbus value as well as the provider's earlier
        # same-device cohort validation (stale_fields is clear and overall
        # effective device freshness is within the normal deadline).
        sibling_fresh = any(
            (field not in snapshot.stale_fields)
            and (sibling_age := _finite(snapshot.source_age_seconds.get(field)))
            is not None
            and 0.0 <= sibling_age <= control_config.stale_data_seconds
            for field in _COHORT_POWER_FIELDS
        )
        if not sibling_fresh:
            return reduce("no fresh same-device FoxESS cohort corroboration")
        report["soc_freshness_basis"] = "same_device_cohort_with_worst_case_discharge"
    else:
        report["soc_freshness_basis"] = "physical_soc_report_with_worst_case_discharge"
    if energy_proven:
        report["soc_freshness_basis"] = "session_physical_energy_ledger_with_gap_debits"
    report["raw_physical_soc_age_seconds"] = round(physical_age, 1)

    deadline = snapshot.next_offpeak_start
    if (
        deadline is None
        or deadline.tzinfo is None
        or now.tzinfo is None
        or "next_offpeak_start" in snapshot.tariff_stale_fields
    ):
        return reduce("no fresh verified future cheap-period deadline")
    until_cheap = (deadline - now).total_seconds() / 3600.0
    if not 0.0 < until_cheap <= 24.0:
        return reduce("cheap-period deadline is not ahead within 24 hours")

    capacity = _finite(simulation_config.battery_capacity_kwh)
    efficiency = _finite(simulation_config.discharge_efficiency)
    expected_house = _finite(
        getattr(forecast_plan, "expected_house_remaining_today_kwh", None)
    )
    if (
        not getattr(forecast_plan, "ready", False)
        or capacity is None
        or capacity <= 0.0
        or efficiency is None
        or not 0.0 < efficiency <= 1.0
        or expected_house is None
        or expected_house < 0.0
    ):
        return reduce("reliable remaining-house forecast unavailable")

    # Solar cannot be counted on when weather confidence is modest. Even at
    # high confidence, conservatively credit at most 25% of solar forecast.
    confidence = _finite(getattr(forecast_plan, "confidence_percent", None))
    expected_solar = _finite(
        getattr(forecast_plan, "expected_solar_remaining_today_kwh", None)
    )
    solar_credit = 0.0
    if (
        confidence is not None
        and confidence >= _SOLAR_CREDIT_MIN_CONFIDENCE
        and expected_solar is not None
        and expected_solar > 0.0
    ):
        solar_credit = min(
            expected_house, expected_solar * _MAX_FORECAST_SOLAR_CREDIT_FRACTION
        )
    net_home = max(expected_house - solar_credit, 0.0)
    buffer_kwh = max(_MIN_HOUSE_BUFFER_KWH, _HOUSE_BUFFER_FRACTION * net_home)
    reserve_percent = max(
        _MIN_PLANNING_RESERVE_PERCENT,
        _finite(simulation_config.battery_reserve_percent) or 0.0,
    )
    reserve_kwh = capacity * reserve_percent / 100.0
    # An old SOC cannot be treated as current merely because the inverter is
    # alive. Assume uninterrupted maximum physical discharge since that
    # particular SOC sample, including discharge-efficiency losses. Never
    # credit unknown charging or optimistic forecast production.
    possible_discharge_kw = max(
        _MIN_CONSERVATIVE_DISCHARGE_KW,
        _finite(simulation_config.max_discharge_kw) or 0.0,
        _finite(control_config.max_discharge_kw) or 0.0,
        _finite(control_config.inverter_limit_kw) or 0.0,
    )
    if energy_proven:
        assert physical_energy_evidence is not None
        tracked_energy = _finite(physical_energy_evidence.lower_bound_kwh)
        if tracked_energy is None or not 0.0 <= tracked_energy <= capacity:
            return reduce("physical energy ledger bound invalid")
        measured_energy_kwh = tracked_energy
        soc_lower_bound = 100.0 * measured_energy_kwh / capacity
        pessimistic_discharge_kwh = max(
            _finite(physical_energy_evidence.pessimistic_discharge_kwh) or 0.0,
            0.0,
        )
    else:
        pessimistic_discharge_kwh = (
            possible_discharge_kw * physical_age / (3600.0 * efficiency)
        )
        soc_lower_bound = max(
            observed - 100.0 * pessimistic_discharge_kwh / capacity,
            0.0,
        )
        measured_energy_kwh = capacity * soc_lower_bound / 100.0
    protected_home_kwh = net_home / efficiency + buffer_kwh
    surplus_kwh = max(measured_energy_kwh - reserve_kwh - protected_home_kwh, 0.0)
    max_export_kw = surplus_kwh / _EXPORT_PROOF_HORIZON_HOURS
    report.update(
        {
            "physical_battery_energy_kwh": round(measured_energy_kwh, 3),
            "physical_soc_lower_bound_percent": round(soc_lower_bound, 3),
            "pessimistic_soc_aging_discharge_kwh": round(pessimistic_discharge_kwh, 3),
            "minimum_battery_reserve_kwh": round(reserve_kwh, 3),
            "forecast_house_energy_kwh": round(expected_house, 3),
            "conservative_solar_credit_kwh": round(solar_credit, 3),
            "protected_home_energy_kwh": round(protected_home_kwh, 3),
            "exportable_physical_energy_kwh": round(surplus_kwh, 3),
            "hours_until_confirmed_cheap": round(until_cheap, 3),
        }
    )
    if surplus_kwh <= 0.001:
        return reduce("all measured battery energy reserved for house and safety")
    if max_export_kw < request - 0.001:
        return reduce("remaining physical surplus bounds this half-hour", max_export_kw)
    report["permitted_export_kw"] = round(request, 3)
    report["status"] = "permitted_with_physical_house_budget"
    return control, report
