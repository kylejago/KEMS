"""Alpha9.123 solar routing economics: read-only, never a FoxESS command."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from math import isfinite
from typing import Any

_MARGIN_PENCE = 0.5
_CONFIDENCE_MIN = 65.0
_SOC_MAX_AGE_SECONDS = 180.0
_EPSILON = 1e-6


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if isfinite(number) else None


def _physical_solar_flow(snapshot: Any) -> dict[str, Any]:
    """Report physical solar/battery/grid evidence separately from the twin.

    There is no independent solar-to-grid submeter. Infer a bounded possible
    PV-to-battery contribution only if all physical sensors are fresh, no EV
    is connected, grid import is negligible, and the same-sample power
    balance agrees. Never feed these reporting estimates into dispatch.
    """
    solar = _num(getattr(snapshot, "solar_power_kw", None))
    house = _num(getattr(snapshot, "house_load_kw", None))
    battery = _num(getattr(snapshot, "battery_power_kw", None))
    grid_import = _num(getattr(snapshot, "grid_import_kw", None))
    grid_export = _num(getattr(snapshot, "grid_export_kw", None))
    charging = round(max(-battery, 0.0), 3) if battery is not None else None
    evidence: dict[str, Any] = {
        "status": "measured_only",
        "measured_pv_kw": solar,
        "measured_house_kw": house,
        "measured_battery_charging_kw": charging,
        "measured_total_grid_export_kw": grid_export,
        "measured_total_grid_import_kw": grid_import,
        "estimated_pv_to_battery_kw": None,
        "metered_pv_to_grid_kw": None,
        "measurement_basis": "FoxESS PV, load, battery and total grid; no solar-only export meter",
        "reporting_only": True,
        "hardware_writes": "forbidden",
    }
    if any(
        value is None or value < 0
        for value in (solar, house, grid_import, grid_export, charging)
    ):
        return evidence
    ages = getattr(snapshot, "source_age_seconds", None)
    if not isinstance(ages, dict):
        return evidence
    for key in (
        "solar_power_kw",
        "house_load_kw",
        "battery_power_kw",
        "grid_import_kw",
        "grid_export_kw",
    ):
        age = _num(ages.get(key))
        if age is None or age < 0 or age > 180:
            return evidence
    if getattr(snapshot, "ev_connected", True):
        return evidence
    # For a fresh near-zero grid import, the PV surplus is the conservative
    # maximum possible source of observed battery charging. Require the entire
    # metered power balance to agree within a small sensor-timing tolerance.
    balance = solar + grid_import - house - charging - grid_export
    if (
        grid_import <= 0.15
        and charging > 0.0
        and solar >= house
        and abs(balance) <= 0.25
    ):
        evidence["status"] = "bounded_physical_inference"
        evidence["estimated_pv_to_battery_kw"] = round(
            min(charging, max(solar - house, 0.0)), 3
        )
    return evidence


def _time(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.astimezone(UTC) if dt.tzinfo else None
    except (ValueError, TypeError):
        return None


def _slot(slots: Any, now: datetime) -> Mapping[str, Any] | None:
    for slot in slots if isinstance(slots, list) else ():
        if not isinstance(slot, Mapping):
            continue
        start, end = _time(slot.get("valid_from")), _time(slot.get("valid_to"))
        if start is not None and end is not None and start <= now < end:
            return slot
    return None


def _future_marginal_rate(
    plan: Mapping[str, Any], now: datetime, need_kwh: float
) -> tuple[float | None, float, str | None]:
    """Price a marginal kWh using spare *physical* planned export capacity.

    Already-allocated peak slots cannot be counted a second time.
    """
    selections = plan.get("selected_slots")
    if not isinstance(selections, list):
        return None, 0.0, None
    possible: list[tuple[float, float, str]] = []
    for item in selections:
        if not isinstance(item, Mapping):
            continue
        end = _time(item.get("valid_to"))
        start = _time(item.get("valid_from"))
        rate = _num(item.get("rate_pence"))
        capacity = _num(item.get("physical_export_capacity_kwh"))
        allocated = _num(item.get("planned_battery_export_kwh"))
        if (
            start is None
            or end is None
            or end <= now
            or end <= start
            or rate is None
            or rate <= 0
            or capacity is None
            or allocated is None
        ):
            continue
        fraction = min(
            (end - max(start, now)).total_seconds() / (end - start).total_seconds(), 1.0
        )
        spare = max(capacity * fraction - allocated, 0.0)
        if spare > _EPSILON:
            possible.append((rate, spare, str(item.get("label") or "")))
    possible.sort(reverse=True)
    remaining = need_kwh
    income = 0.0
    filled = 0.0
    best_slot = None
    for rate, spare, label in possible:
        quantity = min(remaining, spare)
        if quantity <= _EPSILON:
            continue
        best_slot = best_slot or label
        income += quantity * rate
        filled += quantity
        remaining -= quantity
        if remaining <= _EPSILON:
            break
    return (
        (income / filled if remaining <= _EPSILON and filled > 0 else None),
        filled,
        best_slot,
    )


def evaluate_solar_routing_shadow(
    *,
    now: datetime,
    agile_state: Mapping[str, Any],
    snapshot: Any,
    forecast: Any,
    forecast_plan: Any,
    config: Any,
    paid_agile_selected: bool,
) -> dict[str, Any]:
    """Compare solar revenue now to later battery value, not live dispatch.

    Unproven financial or physical inputs never grant Feed-in First.
    Existing cheap-charge, Power Down and Force Discharge take priority.
    """
    now = now.astimezone(UTC)
    solar = _num(getattr(snapshot, "solar_power_kw", None))
    house = _num(getattr(snapshot, "house_load_kw", None))
    battery_kw = _num(getattr(snapshot, "battery_power_kw", None))
    grid_export = _num(getattr(snapshot, "grid_export_kw", None))
    grid_import = _num(getattr(snapshot, "grid_import_kw", None))
    routing = agile_state.get("current_routing_snapshot")
    predicted_export = (
        _num(routing.get("solar_export_kw")) if isinstance(routing, Mapping) else None
    )
    base: dict[str, Any] = {
        "status": "insufficient_evidence",
        "reason": "not evaluated",
        "generated_at": now.isoformat(),
        "scope": "shadow_only",
        "reporting_only": True,
        "hardware_writes": "forbidden",
        "physical_solar_flow": _physical_solar_flow(snapshot),
        "observed_solar_kw": solar,
        "observed_house_kw": house,
        "observed_battery_power_kw": battery_kw,
        "observed_battery_charging_kw": (
            round(max(-battery_kw, 0.0), 3) if battery_kw is not None else None
        ),
        "observed_grid_export_kw": grid_export,
        "observed_grid_import_kw": grid_import,
        "digital_twin_solar_export_kw": predicted_export,
        "digital_twin_vs_grid_export_gap_kw": (
            round(predicted_export - grid_export, 3)
            if predicted_export is not None
            and grid_export is not None
            and battery_kw is not None
            and battery_kw <= 0
            else None
        ),
        "flow_comparison_note": (
            "Estimate versus metered TOTAL export only when battery is not "
            "discharging; no independently measured solar-to-grid split"
        ),
    }

    def verdict(status: str, reason: str, **fields: Any) -> dict[str, Any]:
        return {**base, "status": status, "reason": reason, **fields}

    if not paid_agile_selected or not agile_state.get("live_ready"):
        return verdict("insufficient_evidence", "Agile export price data not ready")
    if getattr(snapshot, "cheap_period_confirmed", False):
        return verdict("higher_priority", "Confirmed cheap charging")
    if getattr(snapshot, "saving_session_active", False):
        return verdict("higher_priority", "Power Down event")
    plan = agile_state.get("rolling_export_plan")
    if not isinstance(plan, Mapping) or not plan.get("available"):
        return verdict("insufficient_evidence", "No physical rolling export plan")
    target = _num(plan.get("current_battery_export_target_kw"))
    if target is None:
        return verdict("insufficient_evidence", "Current battery target unavailable")
    if target > _EPSILON:
        return verdict("higher_priority", "Scheduled Force Discharge already active")
    if set(getattr(snapshot, "stale_fields", ()) or ()) & {
        "solar_power_kw",
        "house_load_kw",
        "battery_power_kw",
        "grid_import_kw",
        "grid_export_kw",
    }:
        return verdict("insufficient_evidence", "Critical power telemetry stale")
    if any(v is None or v < 0 for v in (solar, house, grid_export, grid_import)):
        return verdict(
            "insufficient_evidence", "Physical solar/house/grid readings missing"
        )
    surplus = max(solar - house, 0.0)
    if surplus <= _EPSILON:
        return verdict("no_surplus", "No surplus solar")
    if battery_kw is None:
        return verdict(
            "insufficient_evidence", "Battery power direction is unavailable"
        )
    # The financial opportunity is *divertible PV charging*, not all PV surplus.
    # Solar already exported to the CT would otherwise be valued twice.
    # FoxESS sign convention: negative battery power means charging.
    divertible_kw = min(surplus, max(-battery_kw, 0.0))
    actual_ac_kw = max(solar + battery_kw, 0.0)
    physical_residual_kw = actual_ac_kw - (house + grid_export - grid_import)
    observed_basis = {
        "divertible_solar_charge_kw": round(divertible_kw, 3),
        "physical_ac_balance_residual_kw": round(physical_residual_kw, 3),
        "physical_inverter_ac_kw": round(actual_ac_kw, 3),
    }
    if abs(physical_residual_kw) > 0.5:
        return verdict(
            "insufficient_evidence",
            "Solar/battery/CT readings are not physically coherent",
            **observed_basis,
        )
    if grid_import > 0.1:
        return verdict(
            "insufficient_evidence",
            "Observed day-rate grid import prevents an export-mode proposal",
            **observed_basis,
        )
    if divertible_kw <= 0.05:
        return verdict(
            "no_divertible_charge",
            "No measured solar charging that Feed-in First could redirect",
            **observed_basis,
        )
    slot = _slot(agile_state.get("today_slots"), now)
    price = _num(slot.get("rate_pence")) if slot else None
    if price is None or price <= 0:
        return verdict("insufficient_evidence", "Current Agile export rate unavailable")
    confidence = _num(getattr(forecast, "confidence_percent", None))
    if (
        not getattr(forecast, "ready", False)
        or confidence is None
        or confidence < _CONFIDENCE_MIN
        or not getattr(forecast_plan, "ready", False)
    ):
        return verdict(
            "insufficient_evidence", "Forecast confidence or house plan insufficient"
        )
    predicted_import = _num(
        getattr(forecast_plan, "predicted_day_rate_import_kwh", None)
    )
    if predicted_import is None:
        return verdict(
            "insufficient_evidence", "Forecast expensive import estimate missing"
        )
    if (
        getattr(forecast_plan, "battery_retention_required", False)
        or predicted_import > 0
    ):
        return verdict("keep_self_use", "Battery is needed to avoid expensive imports")

    capacity = _num(getattr(config, "battery_capacity_kwh", None))
    soc = _num(getattr(snapshot, "battery_soc", None))
    ages = getattr(snapshot, "source_age_seconds", None)
    raw_soc_age = _num(ages.get("battery_soc")) if isinstance(ages, Mapping) else None
    max_charge = _num(getattr(config, "max_charge_kw", None))
    export_limit = _num(getattr(config, "export_limit_kw", None))
    inverter_limit = _num(getattr(config, "inverter_limit_kw", None))
    eta_charge = _num(getattr(config, "charge_efficiency", None))
    eta_discharge = _num(getattr(config, "discharge_efficiency", None))
    wear = _num(agile_state.get("battery_wear_assumption_pence_per_discharged_kwh"))
    if (
        capacity is None
        or capacity <= 0
        or soc is None
        or not 0 <= soc <= 100
        or max_charge is None
        or max_charge <= 0
        or export_limit is None
        or export_limit <= 0
        or inverter_limit is None
        or inverter_limit <= 0
        or eta_charge is None
        or not 0 < eta_charge <= 1
        or eta_discharge is None
        or not 0 < eta_discharge <= 1
        or wear is None
        or wear < 0
        or _num(plan.get("planning_soc_percent")) is None
        or _num(plan.get("protected_house_energy_kwh")) is None
    ):
        return verdict(
            "insufficient_evidence", "Physical SOC, reserve, efficiency or wear missing"
        )
    # FoxESS SOC can remain at an old 100% for hours while live battery
    # watts and the separate physical-energy lower bound move. A lower SOC
    # bound is NOT proof of free charging headroom. Never infer a physically
    # full battery, or recommend a new mode, from an old raw SOC register.
    if raw_soc_age is None or raw_soc_age < 0 or raw_soc_age > _SOC_MAX_AGE_SECONDS:
        return verdict(
            "insufficient_evidence",
            "Physical battery SOC report is too old to establish storage headroom",
            physical_soc_age_seconds=raw_soc_age,
            physical_soc_lower_bound_percent=_num(plan.get("planning_soc_percent")),
        )
    remaining_h = max((_time(slot.get("valid_to")) - now).total_seconds() / 3600.0, 0.0)
    export_headroom_kw = max(export_limit - grid_export, 0.0)
    inverter_headroom_kw = max(inverter_limit - actual_ac_kw, 0.0)
    # A mode change may only redirect presently observed battery charging,
    # within both independently metered export and shared KH7 AC headroom.
    # No dedicated PV export register exists; this is still shadow evidence.
    redirect_kw = min(
        divertible_kw, max_charge, export_headroom_kw, inverter_headroom_kw
    )
    headroom_basis = {
        **observed_basis,
        "metered_export_headroom_kw": round(export_headroom_kw, 3),
        "physical_inverter_headroom_kw": round(inverter_headroom_kw, 3),
        "bounded_redirectable_solar_kw": round(redirect_kw, 3),
    }
    if redirect_kw <= 0.05:
        return verdict(
            "no_export_headroom",
            "No independent grid/inverter headroom for solar redirection",
            **headroom_basis,
        )
    redirect_kwh = redirect_kw * min(remaining_h, 0.5)
    extra_kwh = min(
        redirect_kwh,
        max(capacity * (100 - soc) / 100, 0.0) / eta_charge,
    )
    if extra_kwh <= _EPSILON:
        return verdict(
            "feed_in_first_candidate",
            "Battery has no confirmed storage headroom; metered PV is charging",
            current_rate_pence=price,
            metered_redirectable_solar_kwh=round(redirect_kwh, 3),
            **headroom_basis,
        )
    later_rate, spare, label = _future_marginal_rate(
        plan, now, extra_kwh * eta_charge * eta_discharge
    )
    if later_rate is None:
        return verdict(
            "insufficient_evidence",
            "Cannot verify spare future export capacity",
            current_rate_pence=price,
            confirmed_future_spare_kwh=round(spare, 3),
        )
    value_later = eta_charge * eta_discharge * max(later_rate - wear, 0.0)
    advantage = price - value_later
    is_export_better = advantage > _MARGIN_PENCE
    return verdict(
        "feed_in_first_candidate" if is_export_better else "keep_self_use",
        (
            "Export now is worth more"
            if is_export_better
            else "Store for later export is worth more"
        ),
        current_rate_pence=round(price, 4),
        marginal_future_rate_pence=round(later_rate, 4),
        stored_value_pence_per_input_kwh=round(value_later, 4),
        battery_round_trip_efficiency=round(eta_charge * eta_discharge, 4),
        battery_wear_pence_per_kwh=wear,
        forecast_confidence_percent=confidence,
        battery_soc_percent=soc,
        marginal_solar_kwh=round(extra_kwh, 3),
        advantage_pence_per_input_kwh=round(advantage, 4),
        expected_advantage_pence=round(extra_kwh * advantage, 3),
        future_spare_capacity_kwh=round(spare, 3),
        future_price_slot=label,
        decision_margin_pence_per_kwh=_MARGIN_PENCE,
        **headroom_basis,
    )


def publish_solar_routing_shadow(manager: Any, result: Mapping[str, Any]) -> None:
    """Attach diagnostic and publish a separate non-controlling HA state."""
    payload = dict(result)
    manager._state["solar_routing_shadow"] = payload
    manager._set(
        "sensor.kems_solar_routing_shadow",
        str(payload["status"]),
        {"friendly_name": "KEMS solar-routing financial shadow", **payload},
    )
