"""Reporting-only energy-flow overlay for independently booked Happy Hours.

Do not change source/settlement slots, the rolling Agile optimizer, physical SOC,
or FoxESS commands. Only the flow_* dashboard contract is affected. Solar may
serve either home or battery; all remaining demand is forecast as grid import.
"""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from typing import Any

from .kems_core.slot_flow import build_slot_flow


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if isfinite(result) else None


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        date = value
    elif isinstance(value, str):
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return date.astimezone(UTC) if date.tzinfo else None


def overlay_booked_happy_hour_flow(
    state: dict[str, Any],
    *,
    confirmed_bookings: list[dict[str, Any]],
    now: datetime,
    capacity_kwh: float,
    max_charge_kw: float,
    charge_efficiency: float,
    site_import_limit_kw: float,
) -> dict[str, Any]:
    """Project booked future slots without granting import/export authority.

    A physical SOC reading cannot be projected across an unobserved overnight
    recharge. The baseline SOC is explicitly the display model, never a live
    SOC authority. Current/settled slots are never rewritten. A complete
    independently confirmed hourly joined booking is mandatory.
    """
    result: dict[str, Any] = {
        "status": "no_confirmed_future_slots",
        "hardware_writes": "none",
        "scope": "flow_presentation_only",
        "slots_overlaid": 0,
        "modelled_charge_input_kwh": 0.0,
        "modelled_stored_charge_kwh": 0.0,
        "modelled_grid_import_kwh": 0.0,
        "solar_policy": "solar to home or battery; residual supplied by grid",
        "physical_entry_soc_proven": False,
    }
    if (
        not isinstance(state, dict)
        or now.tzinfo is None
        or not all(
            v is not None and v > 0.0
            for v in (
                _number(capacity_kwh),
                _number(max_charge_kw),
                _number(charge_efficiency),
                _number(site_import_limit_kw),
            )
        )
    ):
        result["status"] = "invalid_forecast_inputs"
        return result

    bookings = []
    for item in confirmed_bookings:
        if (
            not isinstance(item, dict)
            or item.get("booking_source") != "octopus_joined_events"
        ):
            continue
        if not item.get("event_id"):
            continue
        start, end = _time(item.get("start")), _time(item.get("end"))
        if start is None or end is None or not start < end:
            continue
        # One booked hour has a separate 16 kWh reward allowance.
        if abs((end - start).total_seconds() - 3600.0) > 1.0:
            continue
        bookings.append((start, end, str(item["event_id"])))
    if not bookings:
        return result

    capacity = float(capacity_kwh)
    charge_kw = float(max_charge_kw)
    efficiency = min(float(charge_efficiency), 1.0)
    site_limit = float(site_import_limit_kw)
    now_utc = now.astimezone(UTC)
    for day_key in ("today_slots", "tomorrow_slots"):
        slots = state.get(day_key)
        if not isinstance(slots, list):
            continue
        slots_sorted = sorted(
            (slot for slot in slots if isinstance(slot, dict)),
            key=lambda item: str(item.get("valid_from") or ""),
        )
        for begin, end, event_id in bookings:
            remaining_hour_kwh = 16.0
            # Take the prior simulated slot SOC as a *forecast* baseline only.
            model_soc: float | None = None
            for slot in slots_sorted:
                until = _time(slot.get("valid_to"))
                if until is not None and until <= begin:
                    soc = _number(slot.get("flow_estimated_soc_percent"))
                    if soc is not None and 0.0 <= soc <= 100.0:
                        model_soc = soc
            for slot in slots_sorted:
                start = _time(slot.get("valid_from"))
                finish = _time(slot.get("valid_to"))
                if (
                    start is None
                    or finish is None
                    or start < begin
                    or finish > end
                    or start < now_utc  # Leave active and settled slots untouched.
                    or finish <= start
                ):
                    continue
                hours = (finish - start).total_seconds() / 3600.0
                home = _number(slot.get("house_load_kwh"))
                solar = _number(slot.get("solar_generation_kwh"))
                if home is None or solar is None or home < 0 or solar < 0:
                    # No invented house/solar forecast to justify free imports.
                    result["status"] = "incomplete_slot_forecast"
                    continue
                solar_home = min(solar, home)
                solar_surplus = max(solar - solar_home, 0.0)
                house_grid = max(home - solar_home, 0.0)
                # Supply unavoidable home load first, not a mandatory
                # grid-only rule that would curtail free solar.
                available_site_import = max(site_limit * hours - house_grid, 0.0)
                remaining_reward = max(remaining_hour_kwh - house_grid, 0.0)
                charge_input = min(
                    charge_kw * hours,
                    available_site_import,
                    remaining_reward,
                )
                if model_soc is not None:
                    stored_space = max(capacity * (100.0 - model_soc) / 100.0, 0.0)
                    charge_input = min(charge_input, stored_space / efficiency)
                solar_battery = min(solar_surplus, charge_input)
                grid_battery = max(charge_input - solar_battery, 0.0)
                solar_export = max(solar_surplus - solar_battery, 0.0)
                grid_import = house_grid + grid_battery
                remaining_hour_kwh = max(remaining_hour_kwh - grid_import, 0.0)
                stored = charge_input * efficiency
                if model_soc is not None:
                    model_soc = min(model_soc + 100.0 * stored / capacity, 100.0)
                slot.update(
                    build_slot_flow(
                        grid_import_kwh=grid_import,
                        solar_generation_kwh=solar,
                        solar_to_home_kwh=solar_home,
                        solar_to_battery_kwh=solar_battery,
                        solar_export_kwh=solar_export,
                        grid_to_battery_kwh=grid_battery,
                        battery_to_home_kwh=0.0,
                        battery_export_kwh=0.0,
                        estimated_soc_percent=model_soc,
                        basis="confirmed booked Happy Hour forecast — NOT physical SOC",
                        scope="future booked reward half-hour",
                    )
                )
                slot["flow_happy_hour_booking_id"] = event_id
                slot["flow_happy_hour_authority"] = (
                    "display only; live meter guards independent"
                )
                result["slots_overlaid"] += 1
                result["modelled_charge_input_kwh"] += charge_input
                result["modelled_stored_charge_kwh"] += stored
                result["modelled_grid_import_kwh"] += grid_import
    if result["slots_overlaid"]:
        result["status"] = "booked_happy_hour_flow_projected"
    for key in (
        "modelled_charge_input_kwh",
        "modelled_stored_charge_kwh",
        "modelled_grid_import_kwh",
    ):
        result[key] = round(result[key], 3)
    return result
