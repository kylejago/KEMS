"""Physical SOC and remaining-house budget veto for paid Agile export.

The rolling Agile plan is a simulation, NOT evidence that its projected SOC
is available in the actual KH7 battery. Only constrain deliberate physical
export; never alter the accounting, history or no-paid-export control path.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from math import isfinite
from typing import Any

from .models import ControlConfig, ControlState, SimulationConfig, Snapshot

_MIN_PLANNING_RESERVE_PERCENT = 15.0
_MIN_HOUSE_BUFFER_KWH = 2.0
_HOUSE_BUFFER_FRACTION = 0.20
_EXPORT_PROOF_HORIZON_HOURS = 0.5
_MAX_FORECAST_SOLAR_CREDIT_FRACTION = 0.25
_SOLAR_CREDIT_MIN_CONFIDENCE = 80.0


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if isfinite(number) else None


def guard_paid_agile_physical_export(
    control: ControlState,
    snapshot: Snapshot,
    forecast_plan: Any,
    simulation_config: SimulationConfig,
    control_config: ControlConfig,
    *,
    now: datetime,
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

    if snapshot.ev_connected is not False or snapshot.ev_charging is not False:
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
    if (
        observed is None
        or not 0.0 <= observed <= 100.0
        or "battery_soc" in snapshot.stale_fields
        or age is None
        or age < 0.0
        or age > control_config.stale_data_seconds
    ):
        return reduce("fresh physical battery SOC unavailable")

    deadline = snapshot.next_offpeak_start
    if deadline is None or deadline.tzinfo is None or now.tzinfo is None:
        return reduce("no verified future cheap-period deadline")
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
    measured_energy_kwh = capacity * observed / 100.0
    protected_home_kwh = net_home / efficiency + buffer_kwh
    surplus_kwh = max(measured_energy_kwh - reserve_kwh - protected_home_kwh, 0.0)
    max_export_kw = surplus_kwh / _EXPORT_PROOF_HORIZON_HOURS
    report.update(
        {
            "physical_battery_energy_kwh": round(measured_energy_kwh, 3),
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
