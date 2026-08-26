"""Canonical Tomorrow SOC handoff for continuous KEMS projections.

Tomorrow is a forward projection, so it must not start from the battery SOC at
whatever time the dashboard happens to be viewed.  It starts from the SOC that
KEMS projects at the overnight cheap-period boundary, then carries the portion
of cheap charging between that boundary and local midnight into tomorrow's
00:00 simulation.

This module changes simulation/reporting continuity only.  It does not alter the
live Agile deadline target, ControlState/shadow commands, Power Down priority,
or the hard block on real hardware writes.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime_base
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    Snapshot,
    SolarForecastState,
)
from .tariff import TariffSettings


def _finite_float(value: Any) -> float | None:
    """Return a finite float-like value, or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def project_tomorrow_midnight_soc(
    *,
    now: datetime,
    current_soc_percent: float,
    forecast_plan: ForecastPlanState,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> tuple[float, dict[str, Any]]:
    """Project SOC at local midnight through the pre-midnight cheap slice.

    Before the cheap period starts, the authoritative handoff source is the
    forecast plan's projected pre-cheap SOC.  Once the cheap period is active,
    the live/current simulated SOC becomes authoritative so elapsed cheap time
    is never charged a second time.
    """
    local_now = now.astimezone(agile.LONDON)
    midnight = datetime.combine(
        local_now.date() + timedelta(days=1),
        time.min,
        tzinfo=agile.LONDON,
    )
    current_soc = min(max(float(current_soc_percent), 0.0), 100.0)

    # Only carry a cheap-window handoff when the configured cheap period really
    # includes the instant immediately before local midnight.
    before_midnight = (midnight - timedelta(seconds=1)).time()
    if not agile._in_window(
        before_midnight,
        tariff.offpeak_start,
        tariff.offpeak_end,
    ):
        return current_soc, {
            "active": False,
            "basis": "no pre-midnight cheap window",
            "current_soc_percent": round(current_soc, 3),
            "midnight_soc_percent": round(current_soc, 3),
            "hardware_writes": "blocked",
        }

    cheap_start = datetime.combine(
        local_now.date(),
        tariff.offpeak_start,
        tzinfo=agile.LONDON,
    )
    if cheap_start >= midnight:
        return current_soc, {
            "active": False,
            "basis": "cheap window does not precede midnight",
            "current_soc_percent": round(current_soc, 3),
            "midnight_soc_percent": round(current_soc, 3),
            "hardware_writes": "blocked",
        }

    projected_precheap = _finite_float(
        forecast_plan.projected_soc_at_cheap_start_percent
    )
    if local_now < cheap_start:
        start_soc = (
            min(max(projected_precheap, 0.0), 100.0)
            if projected_precheap is not None
            else current_soc
        )
        charge_from = cheap_start
        basis = (
            "forecast projected SOC at cheap start"
            if projected_precheap is not None
            else "current SOC fallback at cheap start"
        )
    elif local_now < midnight:
        start_soc = current_soc
        charge_from = local_now
        basis = "current SOC inside active cheap window"
    else:
        start_soc = current_soc
        charge_from = midnight
        basis = "current SOC at/after midnight"

    hours = max((midnight - charge_from).total_seconds() / 3600.0, 0.0)
    capacity = max(float(config.battery_capacity_kwh), 0.1)
    efficiency = min(max(float(config.charge_efficiency), 0.01), 1.0)
    max_charge_kw = max(float(config.max_charge_kw), 0.0)
    stored_needed_kwh = max((100.0 - start_soc) * capacity / 100.0, 0.0)
    max_input_kwh = max_charge_kw * hours
    input_kwh = min(max_input_kwh, stored_needed_kwh / efficiency)
    stored_kwh = input_kwh * efficiency
    midnight_soc = min(start_soc + stored_kwh / capacity * 100.0, 100.0)

    return round(midnight_soc, 3), {
        "active": True,
        "basis": basis,
        "cheap_start": cheap_start.isoformat(),
        "handoff_end": midnight.isoformat(),
        "charge_hours_before_midnight": round(hours, 4),
        "starting_soc_percent": round(start_soc, 3),
        "projected_precheap_soc_percent": (
            round(projected_precheap, 3) if projected_precheap is not None else None
        ),
        "charge_input_kwh_before_midnight": round(input_kwh, 3),
        "stored_charge_kwh_before_midnight": round(stored_kwh, 3),
        "midnight_soc_percent": round(midnight_soc, 3),
        "charge_efficiency": round(efficiency, 4),
        "max_charge_kw": round(max_charge_kw, 3),
        "hardware_writes": "blocked",
    }


class TomorrowSocHandoffAgileSmartExportManager(
    runtime_base.EfficientAgileSmartExportManager
):
    """Rebuild Tomorrow from a physically continuous midnight SOC."""

    async def async_update(
        self,
        *,
        records: list[Snapshot],
        now: datetime,
        config: SimulationConfig,
        learned: LearnedState,
        forecast: SolarForecastState,
        forecast_plan: ForecastPlanState,
        tariff: TariffSettings,
    ) -> dict[str, Any]:
        """Correct a fresh Tomorrow projection after the canonical Alpha7 chain."""
        state = await super().async_update(
            records=records,
            now=now,
            config=config,
            learned=learned,
            forecast=forecast,
            forecast_plan=forecast_plan,
            tariff=tariff,
        )

        # The efficient runtime may legitimately return its five-minute cache.
        # A cached state has already been corrected on the fresh calculation
        # that produced it, so never mix a new ``now`` with old projection data.
        if state.get("generated_at") != now.isoformat():
            return state

        local_now = now.astimezone(agile.LONDON)
        tomorrow_records = self._tomorrow_records(
            local_now,
            learned,
            forecast,
            forecast_plan,
            tariff,
        )
        if len(tomorrow_records) < 2:
            return state

        periods = state.get("periods")
        periods = periods if isinstance(periods, dict) else {}
        today_period = periods.get("today")
        today_period = today_period if isinstance(today_period, dict) else {}

        agile_today = today_period.get("agile_smart_export")
        agile_today = agile_today if isinstance(agile_today, dict) else {}
        full_today = today_period.get("full_kems_forecast")
        full_today = full_today if isinstance(full_today, dict) else {}

        agile_current = _finite_float(agile_today.get("ending_soc_percent"))
        full_current = _finite_float(full_today.get("ending_soc_percent"))
        fallback_soc = max(
            float(config.battery_initial_percent),
            float(config.battery_reserve_percent),
        )
        agile_current = agile_current if agile_current is not None else fallback_soc
        full_current = full_current if full_current is not None else fallback_soc

        agile_midnight, agile_handoff = project_tomorrow_midnight_soc(
            now=now,
            current_soc_percent=agile_current,
            forecast_plan=forecast_plan,
            config=config,
            tariff=tariff,
        )
        full_midnight, full_handoff = project_tomorrow_midnight_soc(
            now=now,
            current_soc_percent=full_current,
            forecast_plan=forecast_plan,
            config=config,
            tariff=tariff,
        )

        tomorrow = self._compare_day(
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

        tomorrow_slots = self._slot_payload(
            local_now.date() + timedelta(days=1),
            tomorrow,
        )
        state["tomorrow_slots"] = tomorrow_slots

        quality = state.get("price_quality")
        quality = quality if isinstance(quality, dict) else {}
        fresh_quality = agile._quality(
            local_now,
            state.get("today_slots") if isinstance(state.get("today_slots"), list) else [],
            tomorrow_slots,
        )
        quality.update(fresh_quality)
        state["price_quality"] = quality
        state["tomorrow_soc_handoff"] = {
            "active": bool(
                agile_handoff.get("active") or full_handoff.get("active")
            ),
            "policy": (
                "today projected pre-cheap SOC -> pre-midnight cheap charge -> "
                "Tomorrow 00:00 SOC"
            ),
            "agile": agile_handoff,
            "full_kems": full_handoff,
            "hardware_writes": "blocked",
        }

        self._state = state
        # Re-publish through the existing Alpha7.52/canonical wrappers so
        # progressive publication metadata is regenerated from corrected slots.
        self._publish(self._state)
        return self.state
