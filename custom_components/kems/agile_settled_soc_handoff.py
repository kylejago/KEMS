"""Rebuild Tomorrow SOC handoff after current-day settlement reconciliation.

Current-day settled shadow outcomes can move the authoritative simulated SOC
materially away from the replay SOC calculated earlier in the coordinator scan.
Tomorrow and the pre-cheap handoff must be rebuilt from that corrected state so
they never carry a stale replay SOC across the 23:30 -> 00:00 boundary.

This is simulation/reporting reconciliation only. Real hardware writes remain
blocked.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from . import agile_smart_export as agile
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    SolarForecastState,
)
from .kems_core.tomorrow_soc_handoff import (
    project_tomorrow_midnight_soc,
    reconcile_precheap_projection,
)
from .tariff import TariffSettings


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _today_display_midnight_soc(
    state: dict[str, Any],
    *,
    now: datetime,
) -> tuple[float, str] | None:
    """Return Today's final displayed SOC at the exact local-midnight boundary.

    The customer-facing Today slot chain is the final reconciled projection after
    settlement, rolling-dispatch and flow-continuity overlays.  Tomorrow must
    inherit that same endpoint rather than re-seeding from an older daily replay.
    """
    slots = state.get("today_slots")
    if not isinstance(slots, list):
        return None

    local_now = now.astimezone(agile.LONDON)
    midnight = datetime.combine(
        local_now.date() + timedelta(days=1),
        time.min,
        tzinfo=agile.LONDON,
    ).astimezone(UTC)

    for slot in reversed(slots):
        if not isinstance(slot, dict):
            continue
        try:
            end = datetime.fromisoformat(str(slot.get("valid_to"))).astimezone(UTC)
        except (TypeError, ValueError):
            continue
        if abs((end - midnight).total_seconds()) > 1.0:
            continue
        for key in ("flow_estimated_soc_percent", "ending_soc_percent"):
            value = _number(slot.get(key))
            if value is not None:
                return min(max(value, 0.0), 100.0), key
    return None


def refresh_tomorrow_handoff_from_settled_soc(
    manager,
    *,
    now: datetime,
    config: SimulationConfig,
) -> dict[str, Any]:
    """Rebuild Tomorrow from the SOC made authoritative by settlement."""
    state = getattr(manager, "_state", None)
    learned = getattr(manager, "_kems_forecast_arbitrage_learned", None)
    forecast = getattr(manager, "_kems_forecast_arbitrage_forecast", None)
    forecast_plan = getattr(manager, "_kems_forecast_arbitrage_plan", None)
    tariff = getattr(manager, "_rolling_tariff", None)

    if not isinstance(state, dict):
        return {"applied": False, "reason": "manager state unavailable"}
    if not isinstance(learned, LearnedState):
        return {"applied": False, "reason": "learned planning context unavailable"}
    if not isinstance(forecast, SolarForecastState):
        return {"applied": False, "reason": "solar forecast context unavailable"}
    if not isinstance(forecast_plan, ForecastPlanState):
        return {"applied": False, "reason": "forecast plan context unavailable"}
    if not isinstance(tariff, TariffSettings):
        return {"applied": False, "reason": "tariff planning context unavailable"}

    local_now = now.astimezone(agile.LONDON)
    tomorrow_records = manager._tomorrow_records(
        local_now,
        learned,
        forecast,
        forecast_plan,
        tariff,
    )
    if len(tomorrow_records) < 2:
        return {"applied": False, "reason": "Tomorrow replay records unavailable"}

    periods = state.get("periods")
    periods = periods if isinstance(periods, dict) else {}
    today_period = periods.get("today")
    today_period = today_period if isinstance(today_period, dict) else {}
    agile_today = today_period.get("agile_smart_export")
    agile_today = agile_today if isinstance(agile_today, dict) else {}
    full_today = today_period.get("full_kems_forecast")
    full_today = full_today if isinstance(full_today, dict) else {}

    fallback_soc = max(
        float(config.battery_initial_percent),
        float(config.battery_reserve_percent),
    )
    agile_current = _number(agile_today.get("ending_soc_percent"))
    full_current = _number(full_today.get("ending_soc_percent"))
    agile_current = agile_current if agile_current is not None else fallback_soc
    full_current = full_current if full_current is not None else fallback_soc

    projected_precheap = _number(forecast_plan.projected_soc_at_cheap_start_percent)
    rolling_plan = state.get("rolling_export_plan")
    rolling_plan = rolling_plan if isinstance(rolling_plan, dict) else {}
    deadline_guard = rolling_plan.get("deadline_guard")
    deadline_guard = deadline_guard if isinstance(deadline_guard, dict) else {}

    rolling_soc = _number(deadline_guard.get("simulated_soc_percent"))
    if rolling_soc is None:
        rolling_soc = _number(rolling_plan.get("simulated_soc_percent"))
    if rolling_soc is None:
        rolling_soc = agile_current

    remaining_capacity = _number(
        deadline_guard.get("solar_aware_remaining_capacity_kwh")
    )
    if remaining_capacity is None:
        remaining_capacity = _number(
            rolling_plan.get("solar_aware_remaining_capacity_kwh")
        )
    reachable_flag = deadline_guard.get("target_physically_reachable_now")
    if not isinstance(reachable_flag, bool):
        reachable_flag = rolling_plan.get("target_physically_reachable_now")
    reachable_flag = reachable_flag if isinstance(reachable_flag, bool) else None

    projected_precheap, precheap_reconciliation = reconcile_precheap_projection(
        projected_precheap_soc_percent=projected_precheap,
        current_soc_percent=rolling_soc,
        remaining_discharge_capacity_kwh=remaining_capacity,
        battery_capacity_kwh=float(config.battery_capacity_kwh),
        discharge_efficiency=float(config.discharge_efficiency),
        reserve_soc_percent=float(config.battery_reserve_percent),
        target_physically_reachable_now=reachable_flag,
    )
    precheap_reconciliation.update(
        {
            "soc_authority": str(
                rolling_plan.get("simulated_soc_source")
                or "settled current-day digital-twin SOC"
            ),
            "settled_current_soc_percent": round(agile_current, 3),
            "rolling_current_soc_percent": (
                round(rolling_soc, 3) if rolling_soc is not None else None
            ),
        }
    )

    handoff_args = {
        "now": now,
        "projected_precheap_soc_percent": projected_precheap,
        "battery_capacity_kwh": float(config.battery_capacity_kwh),
        "max_charge_kw": float(config.max_charge_kw),
        "charge_efficiency": float(config.charge_efficiency),
        "offpeak_start": tariff.offpeak_start,
        "offpeak_end": tariff.offpeak_end,
    }
    agile_midnight, agile_handoff = project_tomorrow_midnight_soc(
        current_soc_percent=agile_current,
        **handoff_args,
    )
    full_midnight, full_handoff = project_tomorrow_midnight_soc(
        current_soc_percent=full_current,
        **handoff_args,
    )
    agile_handoff["precheap_projection_reconciliation"] = dict(precheap_reconciliation)
    full_handoff["precheap_projection_reconciliation"] = dict(precheap_reconciliation)

    # Alpha9.82: once Today has been reconciled into the customer-facing flow
    # timeline, that exact local-midnight endpoint is the authoritative Agile
    # seed for Tomorrow.  Do not splice a separate daily replay back in here.
    display_midnight = _today_display_midnight_soc(state, now=now)
    if display_midnight is not None:
        displayed_soc, displayed_source = display_midnight
        projected_before_display_handoff = agile_midnight
        agile_midnight = displayed_soc
        agile_handoff.update(
            {
                "active": True,
                "basis": "final Today displayed SOC at local midnight",
                "midnight_soc_percent": round(displayed_soc, 3),
                "today_display_source": displayed_source,
                "projected_midnight_soc_before_display_handoff": round(
                    projected_before_display_handoff,
                    3,
                ),
                "today_to_tomorrow_continuity_applied": True,
            }
        )
    else:
        agile_handoff["today_to_tomorrow_continuity_applied"] = False

    tomorrow = manager._compare_day(
        tomorrow_records,
        config,
        tariff,
        agile_midnight,
        full_midnight,
        None,
        projection=True,
    )
    corrected_period = agile._aggregate(
        [tomorrow],
        "tomorrow",
        "Tomorrow forecast",
    )
    existing_tomorrow = periods.get("tomorrow")
    if not isinstance(existing_tomorrow, dict):
        existing_tomorrow = {}
        periods["tomorrow"] = existing_tomorrow
    for key in (
        "ready",
        "days_included",
        "full_kems_forecast",
        "agile_smart_export",
        "comparison",
    ):
        if key in corrected_period:
            existing_tomorrow[key] = corrected_period[key]

    tomorrow_slots = manager._slot_payload(
        local_now.date() + timedelta(days=1),
        tomorrow,
    )
    state["tomorrow_slots"] = tomorrow_slots
    quality = state.get("price_quality")
    quality = quality if isinstance(quality, dict) else {}
    quality.update(
        agile._quality(
            local_now,
            (
                state.get("today_slots")
                if isinstance(state.get("today_slots"), list)
                else []
            ),
            tomorrow_slots,
        )
    )
    state["price_quality"] = quality
    state["tomorrow_soc_handoff"] = {
        "active": bool(agile_handoff.get("active") or full_handoff.get("active")),
        "policy": (
            "settled/current SOC -> protected pre-cheap arrival -> pre-midnight "
            "cheap charge -> Tomorrow 00:00 SOC"
        ),
        "soc_authority": precheap_reconciliation["soc_authority"],
        "agile": agile_handoff,
        "full_kems": full_handoff,
        "hardware_writes": "blocked",
    }
    diagnostic = {
        "applied": True,
        "generated_at": now.isoformat(),
        "soc_authority": precheap_reconciliation["soc_authority"],
        "settled_current_soc_percent": round(agile_current, 3),
        "rolling_current_soc_percent": (
            round(rolling_soc, 3) if rolling_soc is not None else None
        ),
        "projected_precheap_soc_percent": projected_precheap,
        "agile_midnight_soc_percent": agile_midnight,
        "full_kems_midnight_soc_percent": full_midnight,
        "today_display_midnight_soc_percent": (
            display_midnight[0] if display_midnight is not None else None
        ),
        "today_display_midnight_soc_source": (
            display_midnight[1] if display_midnight is not None else None
        ),
        "hardware_writes": "blocked",
    }
    state["settled_soc_handoff_reconciliation"] = diagnostic
    manager._state = state

    # Re-run the existing publication wrappers so dashboards, rolling sensors,
    # current routing and shadow evidence all observe the rebuilt handoff.
    manager._publish(manager._state)
    return diagnostic
