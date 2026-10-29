"""Live paid Agile planning authority from bounded FoxESS physical energy.

This never rewrites the independent digital twin or historical comparison.
The coordinator supplies a single-scan physical evidence object before the
Agile runtime builds its rolling, deadline and forecast plans. Every caller
uses the exact same proof as the final hardware export reserve guard.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

from .kems_core import SimulationConfig
from .kems_core.agile_live_reserve import (
    _HOUSE_BUFFER_FRACTION,
    _MAX_FORECAST_SOLAR_CREDIT_FRACTION,
    _MIN_HOUSE_BUFFER_KWH,
    _MIN_PLANNING_RESERVE_PERCENT,
    _SOLAR_CREDIT_MIN_CONFIDENCE,
    house_forecast_to_cheap_deadline,
    physical_energy_evidence_matches_snapshot,
)


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (ValueError, TypeError):
        return None
    return n if isfinite(n) else None


def physical_planning_soc(
    manager: Any,
    *,
    now: datetime,
    config: SimulationConfig,
) -> tuple[float | None, dict[str, object]]:
    """Return a conservative live SOC for dispatch, or explicit unavailability.

    The only physical authority is a same-scan, same-SOC FoxESS energy proof,
    with fresh directly measured battery power and source freshness.
    In case of any gap or mismatch the caller must keep the twin independent
    and let the physical export guard fail closed.
    """
    reason = "no verified live physical energy evidence"
    context = getattr(manager, "_kems_physical_planning_context", None)
    if not isinstance(context, dict):
        return None, {"available": False, "reason": reason}
    snapshot = context.get("snapshot")
    evidence = context.get("evidence")
    control = context.get("control")
    if snapshot is None or evidence is None or control is None:
        return None, {"available": False, "reason": reason}
    if (
        not physical_energy_evidence_matches_snapshot(
            evidence,
            snapshot,
            control,
            now=now,
        )
        or snapshot.cheap_period_confirmed
        or snapshot.saving_session_active
    ):
        return None, {
            "available": False,
            "reason": "physical source freshness, continuity or priority gate failed",
        }
    cap = _number(config.battery_capacity_kwh)
    energy = _number(evidence.lower_bound_kwh)
    if cap is None or cap <= 0 or energy is None or not 0 <= energy <= cap:
        return None, {
            "available": False,
            "reason": "invalid physical lower bound or configured capacity",
        }
    soc = 100.0 * energy / cap
    return soc, {
        "available": True,
        "source": "verified FoxESS physical energy lower bound",
        "planning_soc_percent": round(soc, 3),
        "physical_energy_lower_bound_kwh": round(energy, 3),
        "physical_soc_report_percent": round(snapshot.battery_soc, 3),
        "physical_soc_anchor": evidence.source_soc_at.isoformat(),
        "physical_samples": evidence.samples,
        "worst_case_gap_kwh": round(evidence.worst_case_gap_kwh, 3),
        "pessimistic_discharge_kwh": round(evidence.pessimistic_discharge_kwh, 3),
        "replay_simulation_soc_preserved": True,
        "scope": "paid_agile_live_control_only",
    }


def conservative_physical_export_budget(
    manager: Any,
    *,
    now: datetime,
    config: SimulationConfig,
) -> tuple[float | None, dict[str, object]]:
    """Use the exact conservative house-reserve arithmetic of the live guard.

    The result is stored battery energy, not delivered AC energy. Missing
    inputs cannot be used to authorise planned paid export.
    """
    soc, proof = physical_planning_soc(manager, now=now, config=config)
    if soc is None or not proof.get("available"):
        return None, {"available": False, "reason": "physical proof unavailable"}
    context = getattr(manager, "_kems_physical_planning_context", None)
    forecast_plan = context.get("forecast_plan") if isinstance(context, dict) else None
    if forecast_plan is None or not getattr(forecast_plan, "ready", False):
        return None, {
            "available": False,
            "reason": "physical house forecast unavailable",
        }
    expected_house = _number(
        getattr(forecast_plan, "expected_house_remaining_today_kwh", None)
    )
    efficiency = _number(config.discharge_efficiency)
    capacity = _number(config.battery_capacity_kwh)
    stored = _number(proof.get("physical_energy_lower_bound_kwh"))
    if (
        expected_house is None
        or expected_house < 0
        or efficiency is None
        or not 0 < efficiency <= 1
        or capacity is None
        or capacity <= 0
        or stored is None
    ):
        return None, {"available": False, "reason": "invalid physical budget inputs"}
    snapshot = context.get("snapshot")
    if snapshot is None:
        # Diagnostic-only simulations have no physical snapshot. Keep the
        # full calendar forecast, not an unverified shortened horizon.
        house_to_cheap = expected_house
        house_basis = "full_calendar_day_missing_physical_snapshot"
    else:
        house_ages = getattr(snapshot, "source_age_seconds", None)
        house_age = (
            _number(house_ages.get("house_load_kw"))
            if isinstance(house_ages, dict)
            else None
        )
        house_to_cheap, house_basis = house_forecast_to_cheap_deadline(
            expected_house,
            now=now,
            deadline=getattr(snapshot, "next_offpeak_start", None),
            house_load_kw=getattr(snapshot, "house_load_kw", None),
            house_age_seconds=house_age,
            house_stale="house_load_kw" in getattr(snapshot, "stale_fields", ()),
        )
    confidence = _number(getattr(forecast_plan, "confidence_percent", None))
    expected_solar = _number(
        getattr(forecast_plan, "expected_solar_remaining_today_kwh", None)
    )
    credit = 0.0
    if (
        house_basis.startswith("full_calendar_day")
        and confidence is not None
        and confidence >= _SOLAR_CREDIT_MIN_CONFIDENCE
        and expected_solar is not None
        and expected_solar > 0
    ):
        credit = min(
            house_to_cheap, expected_solar * _MAX_FORECAST_SOLAR_CREDIT_FRACTION
        )
    net_home = max(house_to_cheap - credit, 0.0)
    buffer = max(_MIN_HOUSE_BUFFER_KWH, net_home * _HOUSE_BUFFER_FRACTION)
    protected = net_home / efficiency + buffer
    reserve_percent = max(
        _MIN_PLANNING_RESERVE_PERCENT,
        _number(config.battery_reserve_percent) or 0.0,
    )
    reserve = capacity * reserve_percent / 100.0
    budget = max(stored - reserve - protected, 0.0)
    return budget, {
        "available": True,
        "basis": "same-scan physical guard house forecast and buffers",
        "physical_energy_lower_bound_kwh": round(stored, 3),
        "minimum_reserve_kwh": round(reserve, 3),
        "protected_house_stored_kwh": round(protected, 3),
        "calendar_day_house_forecast_kwh": round(expected_house, 3),
        "forecast_house_until_cheap_kwh": round(house_to_cheap, 3),
        "forecast_house_horizon_basis": house_basis,
        "independent_house_buffer_kwh": round(buffer, 3),
        "solar_credit_kwh": round(credit, 3),
        "exportable_stored_kwh": round(budget, 3),
        "exportable_ac_kwh": round(budget * efficiency, 3),
    }
