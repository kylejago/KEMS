"""Verified physical battery headroom preparation for joined Octopus Happy Hours.

This is a *request* inside the existing paid-Agile command pipeline, never
an independent FoxESS write. The physical SOC/EV/home/DNO guards and the
FoxESS backend retain final authority, including the ability to veto it.
The independent digital-twin schedule is not rewritten.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Mapping

from .happy_hour_auto_join import confirmed_booking_windows


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return result.astimezone(UTC) if result.tzinfo else None


def _joined_window_confirmed(
    booking: Mapping[str, Any], start: datetime, end: datetime
) -> bool:
    if booking.get("status") != "booked":
        return False
    return any(
        window["start"] == start and window["end"] == end
        for window in confirmed_booking_windows(booking)
    )


def _physical_prep_slots(
    agile_state: Mapping[str, Any],
    *,
    now: datetime,
    event_start: datetime,
    requested_kwh: float,
    max_export_kw: float,
) -> list[dict[str, Any]]:
    """Use only real positive-price pre-event slots, highest value first."""
    candidates: list[dict[str, Any]] = []
    for slot in agile_state.get("today_slots", ()):
        if not isinstance(slot, dict):
            continue
        start = _dt(slot.get("valid_from"))
        end = _dt(slot.get("valid_to"))
        rate = _number(slot.get("rate_pence"))
        if (
            start is None
            or end is None
            or rate is None
            or rate <= 0
            or end <= now
            or start >= event_start
        ):
            continue
        usable_start = max(now, start)
        usable_end = min(event_start, end)
        if usable_end <= usable_start:
            continue
        available_hours = (usable_end - usable_start).total_seconds() / 3600.0
        candidates.append(
            {
                "valid_from": start.isoformat(),
                "valid_to": end.isoformat(),
                "rate_pence": rate,
                "capacity_kwh": max_export_kw * available_hours,
                "available_hours": available_hours,
            }
        )
    remaining = max(requested_kwh, 0.0)
    selected: list[dict[str, Any]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (-item["rate_pence"], item["valid_from"]),
    ):
        if remaining <= 0.001:
            break
        allocation = min(remaining, candidate["capacity_kwh"])
        if allocation <= 0.001:
            continue
        selected.append(
            {
                "valid_from": candidate["valid_from"],
                "valid_to": candidate["valid_to"],
                "rate_pence": candidate["rate_pence"],
                "planned_battery_export_kwh": round(allocation, 3),
                "physical_happy_hour_headroom": True,
            }
        )
        remaining -= allocation
    return sorted(selected, key=lambda item: item["valid_from"])


def apply_verified_happy_hour_preparation(
    control: Any,
    *,
    booking: Mapping[str, Any],
    context: Mapping[str, Any],
    agile_state: Mapping[str, Any],
    snapshot: Any,
    now: datetime,
    config: Any,
    simulation_config: Any,
    power_down_active: bool,
    agile_selected: bool,
) -> tuple[Any, dict[str, Any]]:
    """Build physical headroom intent; final live export guards still run.

    An Octopus-confirmed *future* joined window and same-scan physical budget
    are mandatory. Simulated SOC, an unjoined manual event or a price forecast
    alone cannot authorise discharge.
    """
    result: dict[str, Any] = {
        "status": "inactive",
        "scope": "physical_preparation_request_before_existing_safety_guards",
        "requested_export_kw": 0.0,
        "authorised_final_export_kw": None,
        "selected_slots": [],
        "hardware_writes": "none_in_this_module",
    }

    def stop(reason: str) -> tuple[Any, dict[str, Any]]:
        result["status"] = reason
        return control, result

    start, end = _dt(context.get("start")), _dt(context.get("end"))
    if (
        not agile_selected
        or context.get("source") != "octopus_energy"
        or context.get("mode") not in {"preparation", "ready"}
        or context.get("preparation_in_current_horizon") is not True
        or start is None
        or end is None
        or not now.tzinfo
        or not now < start < end
    ):
        return stop("no_upcoming_confirmed_eligible_event")
    if not _joined_window_confirmed(booking, start, end):
        return stop("joined_window_not_independently_confirmed")
    result["event_start"] = start.isoformat()
    result["event_end"] = end.isoformat()
    if (
        power_down_active
        or bool(getattr(snapshot, "saving_session_active", False))
        or bool(getattr(snapshot, "cheap_period_confirmed", False))
        or bool(getattr(config, "emergency_stop", False))
    ):
        return stop("higher_priority_event_or_cheap_period")
    if (
        getattr(control, "operating_mode", "") != "control"
        or not getattr(control, "control_enabled", False)
        or not getattr(control, "commissioned", False)
        or not getattr(control, "data_fresh", False)
        or not getattr(control, "plan_safe", False)
        or not getattr(control, "grid_available", False)
        or getattr(control, "island_mode_active", True)
        or not getattr(control, "desired_grid_export_allowed", False)
        or getattr(control, "site_import_limit_exceeded", True)
        or getattr(control, "alpha969_routing_shadow_only", False)
    ):
        return stop("physical_control_gate_closed")
    if (
        context.get("physical_soc_verified") is not True
        or context.get("physical_charge_headroom_verified") is not True
        or _number(context.get("current_physical_soc_percent")) is None
        or _number(getattr(snapshot, "battery_soc", None))
        != _number(context.get("current_physical_soc_percent"))
    ):
        return stop("no_verified_same_scan_physical_soc")

    rolling = agile_state.get("rolling_export_plan")
    if not isinstance(rolling, dict) or not rolling.get("available"):
        return stop("rolling_plan_unavailable")
    evidence = rolling.get("physical_house_budget_evidence")
    physical = rolling.get("physical_planning_evidence")
    if (
        not isinstance(evidence, dict)
        or not evidence.get("available")
        or not isinstance(physical, dict)
        or not physical.get("available")
        or rolling.get("generated_at") != agile_state.get("generated_at")
    ):
        return stop("same_scan_physical_house_budget_unverified")
    needed = _number(context.get("physical_required_headroom_export_kwh"))
    budget = _number(evidence.get("exportable_ac_kwh"))
    if needed is None or budget is None or min(needed, budget) < 0.0:
        return stop("invalid_physical_headroom_or_house_budget")
    result["physical_required_headroom_export_kwh"] = round(needed, 3)
    result["protected_ac_export_budget_kwh"] = round(budget, 3)
    requested_energy = min(needed, budget)
    result["physically_budgeted_preparation_kwh"] = round(requested_energy, 3)
    if requested_energy <= 0.001:
        return stop("headroom_ready_or_house_reserve_protected")

    max_discharge = _number(getattr(config, "max_discharge_kw", None))
    max_export = _number(getattr(config, "export_limit_kw", None))
    max_inverter = _number(getattr(config, "inverter_limit_kw", None))
    max_battery = _number(getattr(simulation_config, "max_discharge_kw", None))
    if any(
        x is None or x <= 0.0
        for x in (max_discharge, max_export, max_inverter, max_battery)
    ):
        return stop("physical_power_limit_unknown")
    physical_kw = min(max_discharge, max_export, max_inverter, max_battery)
    selected = _physical_prep_slots(
        agile_state,
        now=now,
        event_start=start,
        requested_kwh=requested_energy,
        max_export_kw=physical_kw,
    )
    allocated = sum(item["planned_battery_export_kwh"] for item in selected)
    result.update(
        {
            "selected_slots": selected,
            "allocated_preparation_kwh": round(allocated, 3),
            "preparation_shortfall_kwh": round(
                max(requested_energy - allocated, 0.0), 3
            ),
        }
    )
    current_kw = 0.0
    for slot in selected:
        slot_start, slot_end = _dt(slot["valid_from"]), _dt(slot["valid_to"])
        if slot_start is None or slot_end is None or not slot_start <= now < slot_end:
            continue
        hours_remaining = (slot_end - now).total_seconds() / 3600.0
        if hours_remaining > 0:
            current_kw += slot["planned_battery_export_kwh"] / hours_remaining
    if current_kw <= 0.001:
        return stop("awaiting_selected_physical_preparation_slot")

    house_kw = max(
        _number(getattr(control, "desired_battery_to_home_power_kw", 0.0)) or 0.0,
        0.0,
    )
    solar_kw = _number(getattr(snapshot, "solar_power_kw", None))
    if solar_kw is None or solar_kw < 0.0:
        return stop("physical_solar_power_unavailable")
    current_kw = min(
        current_kw,
        physical_kw,
        max(max_discharge - house_kw, 0.0),
        max(max_inverter - solar_kw - house_kw, 0.0),
    )
    if current_kw <= 0.001:
        return stop("no_current_physical_inverter_headroom")
    total = house_kw + current_kw
    result.update(
        {
            "status": "submitted_to_independent_physical_guard",
            "requested_export_kw": round(current_kw, 3),
            "note": (
                "Confirmed event headroom has priority over ordinary Agile "
                "economic slot selection; full FoxESS EV/SOC/DNO controls apply."
            ),
        }
    )
    return (
        replace(
            control,
            operating_reason="happy_hour_verified_physical_preparation",
            desired_work_mode="Feed-in First",
            desired_battery_export_power_kw=round(current_kw, 3),
            desired_total_discharge_power_kw=round(total, 3),
            desired_charge_power_kw=0.0,
            total_kh7_ac_output_kw=round(solar_kw + total, 3),
            kh7_output_headroom_kw=round(max(max_inverter - solar_kw - total, 0.0), 3),
            next_action=(
                "Confirmed Octopus Happy Hour — create verified physical "
                "battery headroom under existing paid-Agile safety guards"
            ),
            real_backend_available=False,
            commands_permitted=False,
        ),
        result,
    )
