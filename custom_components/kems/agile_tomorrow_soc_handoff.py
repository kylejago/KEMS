"""Canonical Tomorrow SOC handoff for continuous KEMS projections.

Tomorrow is a forward projection, so it must not start from the battery SOC at
whatever time the dashboard happens to be viewed. It starts from the SOC KEMS
projects at the overnight cheap boundary, plus cheap charging up to midnight.

This module changes simulation/reporting continuity only. It does not alter live
Agile targets, ControlState/shadow commands, Power Down priority, or hardware
write permissions.
"""

from __future__ import annotations

from datetime import datetime, timedelta
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
from .kems_core.tomorrow_soc_handoff import (
    project_tomorrow_midnight_soc,
    reconcile_precheap_projection,
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

        # A cached state was already corrected when its fresh calculation ran.
        # Never mix a new ``now`` with cached projection inputs.
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

        fallback_soc = max(
            float(config.battery_initial_percent),
            float(config.battery_reserve_percent),
        )
        agile_current = _finite_float(agile_today.get("ending_soc_percent"))
        full_current = _finite_float(full_today.get("ending_soc_percent"))
        agile_current = agile_current if agile_current is not None else fallback_soc
        full_current = full_current if full_current is not None else fallback_soc
        projected_precheap = _finite_float(
            forecast_plan.projected_soc_at_cheap_start_percent
        )

        rolling_plan = state.get("rolling_export_plan")
        rolling_plan = rolling_plan if isinstance(rolling_plan, dict) else {}
        deadline_guard = rolling_plan.get("deadline_guard")
        deadline_guard = deadline_guard if isinstance(deadline_guard, dict) else {}
        rolling_soc = _finite_float(deadline_guard.get("simulated_soc_percent"))
        if rolling_soc is None:
            rolling_soc = _finite_float(rolling_plan.get("simulated_soc_percent"))
        remaining_capacity = _finite_float(
            deadline_guard.get("solar_aware_remaining_capacity_kwh")
        )
        if remaining_capacity is None:
            remaining_capacity = _finite_float(
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
        agile_handoff["precheap_projection_reconciliation"] = dict(
            precheap_reconciliation
        )
        full_handoff["precheap_projection_reconciliation"] = dict(
            precheap_reconciliation
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
                "today achievable pre-cheap SOC -> pre-midnight cheap charge -> "
                "Tomorrow 00:00 SOC"
            ),
            "agile": agile_handoff,
            "full_kems": full_handoff,
            "hardware_writes": "blocked",
        }

        self._state = state
        # Re-run existing publication wrappers from corrected Tomorrow slots.
        self._publish(self._state)
        return self.state
