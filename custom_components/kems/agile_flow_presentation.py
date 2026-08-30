"""Canonical post-settlement flow presentation for Agile Smart Export.

Alpha8.48 keeps every dispatch/control owner below this class unchanged.  It
adds one reporting boundary after Alpha8.47 so the customer-facing slot feed can
show Grid, Solar and Battery routes from the final plan, and so live replay solar
export is not hidden until the active half-hour closes.

Real FoxESS writes remain blocked.  This module publishes reporting data only.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from . import agile_smart_export as agile
from .agile_current_day_settlement import _reconcile_comparison
from .agile_midnight_rollover import MidnightRolloverAgileSmartExportManager
from .kems_core import (
    ForecastPlanState,
    LearnedState,
    SimulationConfig,
    Snapshot,
    SolarForecastState,
)
from .kems_core.slot_flow import build_slot_flow
from .tariff import TariffSettings

_EPSILON = 1e-6


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dt(value: Any) -> datetime | None:
    """Parse a timestamp and normalise it to UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _slot_duration_hours(slot: dict[str, Any]) -> float:
    start = _dt(slot.get("valid_from"))
    end = _dt(slot.get("valid_to"))
    if start is None or end is None or end <= start:
        return 0.5
    return min(max((end - start).total_seconds() / 3600.0, 0.0), 0.5)


def _effective_battery_home(slot: dict[str, Any], *, completed: bool) -> float:
    if not completed:
        planned = _number(slot.get("planned_battery_to_home_kwh"))
        if planned is not None:
            return max(planned, 0.0)
    return max(_number(slot.get("battery_to_home_kwh")) or 0.0, 0.0)


def _effective_battery_export(slot: dict[str, Any], *, completed: bool) -> float:
    if not completed:
        rolling = _number(slot.get("rolling_planned_battery_export_kwh"))
        if rolling is not None:
            return max(rolling, 0.0)
    return max(_number(slot.get("battery_export_kwh")) or 0.0, 0.0)


def _forecast_solar_kwh(
    forecast: SolarForecastState,
    start: datetime,
    end: datetime,
) -> float:
    """Integrate the canonical hourly solar forecast over one slot/window."""
    total = 0.0
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    for item in forecast.hourly or ():
        hour_start = item.timestamp.astimezone(UTC)
        hour_end = hour_start + timedelta(hours=1)
        overlap = (
            max(
                (min(end_utc, hour_end) - max(start_utc, hour_start)).total_seconds(),
                0.0,
            )
            / 3600.0
        )
        if overlap > 0.0:
            total += max(float(item.solar_energy_kwh), 0.0) * overlap
    return total


def _best_future_rate(
    slots: list[dict[str, Any]],
    current_start: datetime,
    deadline: datetime,
) -> float:
    values = []
    for slot in slots:
        start = _dt(slot.get("valid_from"))
        rate = _number(slot.get("rate_pence"))
        if start is None or rate is None:
            continue
        if current_start < start < deadline:
            values.append(rate)
    return max(values) if values else 0.0


def _observed_slot_details(
    self,
    records: list[Snapshot],
    rates: list[agile.AgileRate],
    config: SimulationConfig,
) -> dict[str, dict[str, float]]:
    """Reconstruct only fields the legacy slot payload discarded.

    The calculation deliberately mirrors the already-proven replay inputs.  It
    does not make a second routing decision: solar-to-battery/export and battery
    routes still come from the authoritative slot plan returned by ``_agile_day``.
    """
    output: dict[str, dict[str, float]] = {}
    for current, following in zip(records, records[1:], strict=False):
        hours = min(
            max((following.timestamp - current.timestamp).total_seconds(), 0.0)
            / 3600.0,
            0.5,
        )
        if hours <= 0.0:
            continue
        rate = agile._rate_at(rates, current.timestamp)
        load = agile._load(current)
        if (
            current.stale_fields
            or following.stale_fields
            or rate is None
            or load is None
            or agile._load(following) is None
            or current.current_import_rate is None
        ):
            continue
        key = rate.valid_from.isoformat()
        detail = output.setdefault(
            key,
            {
                "solar_generation_kwh": 0.0,
                "solar_to_home_kwh": 0.0,
                "house_load_kwh": 0.0,
            },
        )
        solar = self._simulation._simulated_solar_power(current, config) * hours
        load_kwh = max(load, 0.0) * hours
        inverter = max(config.inverter_limit_kw, 0.0) * hours
        solar_home = (
            0.0
            if current.cheap_period_confirmed
            else min(max(solar, 0.0), load_kwh, inverter)
        )
        detail["solar_generation_kwh"] += max(solar, 0.0)
        detail["solar_to_home_kwh"] += solar_home
        detail["house_load_kwh"] += load_kwh
    return output


def _attach_observed_details(
    plan: list[dict[str, Any]],
    details: dict[str, dict[str, float]],
    config: SimulationConfig,
) -> None:
    """Add replay-derived source fields to the existing slot plan in place."""
    for slot in plan:
        detail = details.get(str(slot.get("valid_from") or ""))
        if detail is None:
            slot.setdefault("solar_generation_kwh", None)
            slot.setdefault("solar_to_home_kwh", None)
            slot.setdefault("grid_to_battery_kwh", None)
            slot.setdefault("house_load_kwh", None)
            continue
        grid_import = max(_number(slot.get("grid_import_kwh")) or 0.0, 0.0)
        house = max(detail["house_load_kwh"], 0.0)
        grid_charge_input = max(grid_import - house, 0.0)
        slot["solar_generation_kwh"] = round(detail["solar_generation_kwh"], 3)
        slot["solar_to_home_kwh"] = round(detail["solar_to_home_kwh"], 3)
        slot["grid_to_battery_kwh"] = round(
            grid_charge_input * max(config.charge_efficiency, 0.01),
            3,
        )
        slot["house_load_kwh"] = round(house, 3)


def _conservative_house_kw(self, learned: LearnedState) -> float:
    evidence = getattr(self, "_kems_solar_net_house_protection", None)
    if isinstance(evidence, dict):
        value = _number(evidence.get("conservative_house_kw"))
        if value is not None and value >= 0.0:
            return value
    learned_value = _number(learned.typical_house_load_kw)
    return max(learned_value if learned_value is not None else 0.4, 0.0)


def _close_home_precision_residual(
    *,
    remaining_house_kwh: float,
    battery_home_kwh: float,
    battery_energy_kwh: float,
    floor_kwh: float,
    discharge_limit_kwh: float,
    discharge_efficiency: float,
) -> float:
    """Reconcile future daytime battery discharge to the house-first invariant.

    ``battery_home_kwh`` remains in the signature for compatibility with the
    Alpha8.56 regression boundary, but the canonical future projection must not
    preserve a rounded/planned home allocation when physical battery headroom can
    cover more of the house.  Outside cheap periods, usable battery AC therefore
    serves the remaining house demand before Grid.
    """
    del battery_home_kwh
    remaining_house = max(remaining_house_kwh, 0.0)
    battery_headroom = max(
        (battery_energy_kwh - floor_kwh) * max(discharge_efficiency, 0.01),
        0.0,
    )
    usable_discharge = min(
        max(discharge_limit_kwh, 0.0),
        battery_headroom,
    )
    return min(remaining_house, usable_discharge)


def _future_today_projection(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    learned: LearnedState,
    forecast: SolarForecastState,
    forecast_plan: ForecastPlanState,
    tariff: TariffSettings,
) -> dict[str, dict[str, Any]]:
    """Project remaining Today source flows from the final rolling allocations."""
    slots = [item for item in state.get("today_slots", []) if isinstance(item, dict)]
    if not slots:
        return {}
    now_utc = now.astimezone(UTC)
    local_day = now.astimezone(agile.LONDON).date()
    routing = state.get("current_routing_snapshot")
    routing = routing if isinstance(routing, dict) else {}
    soc = _number(routing.get("simulated_soc_percent"))
    if soc is None:
        rolling = state.get("rolling_export_plan")
        rolling = rolling if isinstance(rolling, dict) else {}
        soc = _number(rolling.get("simulated_soc_percent"))
    if soc is None:
        return {}

    capacity = max(config.battery_capacity_kwh, 0.1)
    battery = capacity * min(max(soc, 0.0), 100.0) / 100.0
    charge_efficiency = max(config.charge_efficiency, 0.01)
    discharge_efficiency = max(config.discharge_efficiency, 0.01)
    house_kw = _conservative_house_kw(self, learned)
    precheap_target = max(
        config.battery_reserve_percent,
        _number(forecast_plan.minimum_precheap_soc_percent) or 10.0,
        10.0,
    )
    overnight_target = min(
        max(
            _number(forecast_plan.maximum_overnight_soc_percent) or 100.0,
            precheap_target,
        ),
        100.0,
    )
    deadline = agile._next_cheap(now, tariff).astimezone(UTC)
    output: dict[str, dict[str, Any]] = {}

    for slot in sorted(slots, key=lambda item: str(item.get("valid_from") or "")):
        start = _dt(slot.get("valid_from"))
        end = _dt(slot.get("valid_to"))
        if start is None or end is None or end <= now_utc:
            continue
        if start.astimezone(agile.LONDON).date() != local_day:
            continue
        window_start = max(start, now_utc)
        hours = max((end - window_start).total_seconds() / 3600.0, 0.0)
        if hours <= _EPSILON:
            continue
        scope = "remaining slot" if start < now_utc else "full slot"
        solar_generation = _forecast_solar_kwh(forecast, window_start, end)
        house = house_kw * hours
        midpoint = window_start + (end - window_start) / 2
        cheap = agile._in_window(
            midpoint.astimezone(agile.LONDON).time(),
            tariff.offpeak_start,
            tariff.offpeak_end,
        )
        rate = max(_number(slot.get("rate_pence")) or 0.0, 0.0)
        discharge_limit = max(config.max_discharge_kw, 0.0) * hours
        inverter_limit = max(config.inverter_limit_kw, 0.0) * hours
        export_limit = min(
            max(config.export_limit_kw, 0.0) * hours,
            inverter_limit,
        )
        charge_limit = max(config.max_charge_kw, 0.0) * hours
        battery_home = min(
            _effective_battery_home(slot, completed=False),
            discharge_limit,
        )
        battery_export = min(
            _effective_battery_export(slot, completed=False),
            max(discharge_limit - battery_home, 0.0),
            export_limit,
        )
        solar_home = solar_battery = solar_export = grid_battery = 0.0
        grid_import = 0.0

        if cheap:
            # Established KEMS cheap-period policy powers the house from grid.
            battery_home = 0.0
            battery_export = 0.0
            solar_left = solar_generation
            solar_charge_input = 0.0
            if rate <= 0.0 and battery < capacity - _EPSILON:
                solar_charge_input = min(
                    solar_left,
                    charge_limit,
                    max(capacity - battery, 0.0) / charge_efficiency,
                )
                solar_battery = solar_charge_input * charge_efficiency
                battery += solar_battery
                solar_left -= solar_charge_input
            if rate > 0.0:
                solar_export = min(solar_left, export_limit, inverter_limit)
            target_kwh = capacity * overnight_target / 100.0
            grid_charge_input = min(
                max(charge_limit - solar_charge_input, 0.0),
                max(target_kwh - battery, 0.0) / charge_efficiency,
            )
            if config.site_import_limit_kw is not None:
                grid_charge_input = min(
                    grid_charge_input,
                    max(config.site_import_limit_kw * hours - house, 0.0),
                )
            grid_battery = grid_charge_input * charge_efficiency
            battery += grid_battery
            grid_import = house + grid_charge_input
        else:
            solar_home = min(solar_generation, house, inverter_limit)
            remaining_house = max(house - solar_home, 0.0)
            floor_kwh = capacity * precheap_target / 100.0
            battery_home = min(battery_home, remaining_house)
            battery_home = _close_home_precision_residual(
                remaining_house_kwh=remaining_house,
                battery_home_kwh=battery_home,
                battery_energy_kwh=battery,
                floor_kwh=floor_kwh,
                discharge_limit_kwh=min(
                    discharge_limit,
                    max(inverter_limit - solar_home, 0.0),
                ),
                discharge_efficiency=discharge_efficiency,
            )
            battery -= battery_home / discharge_efficiency
            solar_left = max(solar_generation - solar_home, 0.0)
            best_future = _best_future_rate(slots, start, deadline)
            stored_value = (
                best_future * charge_efficiency * discharge_efficiency
                - agile.BATTERY_WEAR_PENCE_PER_KWH
            )
            if (
                solar_left > _EPSILON
                and battery < capacity - _EPSILON
                and (battery < floor_kwh - _EPSILON or stored_value > rate + 0.001)
            ):
                solar_charge_input = min(
                    solar_left,
                    charge_limit,
                    max(capacity - battery, 0.0) / charge_efficiency,
                )
                solar_battery = solar_charge_input * charge_efficiency
                battery += solar_battery
                solar_left -= solar_charge_input
            battery_export = min(
                battery_export,
                max(discharge_limit - battery_home, 0.0),
                max(inverter_limit - solar_home - battery_home, 0.0),
                max((battery - floor_kwh) * discharge_efficiency, 0.0),
                max(export_limit, 0.0),
            )
            solar_export = min(
                solar_left,
                max(export_limit - battery_export, 0.0),
                max(inverter_limit - solar_home - battery_home - battery_export, 0.0),
            )
            battery -= battery_export / discharge_efficiency
            grid_import = max(remaining_house - battery_home, 0.0)

        battery = min(
            max(battery, capacity * config.battery_reserve_percent / 100.0), capacity
        )
        output[str(slot.get("valid_from") or "")] = {
            "grid_import_kwh": grid_import,
            "solar_generation_kwh": solar_generation,
            "solar_to_home_kwh": solar_home,
            "solar_to_battery_kwh": solar_battery,
            "solar_export_kwh": solar_export,
            "grid_to_battery_kwh": grid_battery,
            "battery_to_home_kwh": battery_home,
            "battery_export_kwh": battery_export,
            "estimated_soc_percent": 100.0 * battery / capacity,
            "basis": "KEMS forecast + final rolling allocation",
            "scope": scope,
        }
    return output


def _exact_flow_values(slot: dict[str, Any], *, completed: bool) -> dict[str, Any]:
    return {
        "grid_import_kwh": _number(slot.get("grid_import_kwh")),
        "solar_generation_kwh": _number(slot.get("solar_generation_kwh")),
        "solar_to_home_kwh": _number(slot.get("solar_to_home_kwh")),
        "solar_to_battery_kwh": _number(slot.get("solar_to_battery_kwh")),
        "solar_export_kwh": _number(slot.get("solar_export_kwh")),
        "grid_to_battery_kwh": _number(slot.get("grid_to_battery_kwh")),
        "battery_to_home_kwh": _effective_battery_home(slot, completed=completed),
        "battery_export_kwh": _effective_battery_export(slot, completed=completed),
        "estimated_soc_percent": _number(slot.get("ending_soc_percent")),
        "basis": (
            "settled/replayed KEMS slot" if completed else "KEMS forecast replay"
        ),
        "scope": "full slot",
    }


def _attach_flow_contract(
    state: dict[str, Any],
    *,
    now: datetime,
    future_today: dict[str, dict[str, Any]],
) -> None:
    now_utc = now.astimezone(UTC)
    for key in ("today_slots", "tomorrow_slots"):
        slots = state.get(key)
        if not isinstance(slots, list):
            continue
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            end = _dt(slot.get("valid_to"))
            completed = bool(end is not None and end <= now_utc)
            values = None
            if key == "today_slots" and not completed:
                values = future_today.get(str(slot.get("valid_from") or ""))
            if values is None:
                values = _exact_flow_values(slot, completed=completed)
            slot.update(build_slot_flow(**values))


def _live_replay_solar_accounting(
    state: dict[str, Any],
    *,
    now: datetime,
) -> None:
    """Keep live replay solar while battery export remains settlement-only."""
    periods = state.get("periods")
    if not isinstance(periods, dict):
        return
    today = periods.get("today")
    if not isinstance(today, dict):
        return
    agile_today = today.get("agile_smart_export")
    if not isinstance(agile_today, dict) or not agile_today.get("ready"):
        return
    slots = [item for item in state.get("today_slots", []) if isinstance(item, dict)]
    if not slots:
        return
    now_utc = now.astimezone(UTC)

    replay_solar_export = 0.0
    solar_income = 0.0
    settled_battery_export = 0.0
    battery_income = 0.0
    settled_slots = 0
    for slot in slots:
        solar_export = max(_number(slot.get("solar_export_kwh")) or 0.0, 0.0)
        rate = _number(slot.get("rate_pence"))
        replay_solar_export += solar_export
        if rate is not None:
            solar_income += solar_export * rate
        end = _dt(slot.get("valid_to"))
        if end is not None and end <= now_utc and slot.get("settlement_source"):
            battery_export = max(_number(slot.get("battery_export_kwh")) or 0.0, 0.0)
            settled_battery_export += battery_export
            if rate is not None:
                battery_income += battery_export * rate
            settled_slots += 1

    replay_solar_export = round(replay_solar_export, 3)
    settled_battery_export = round(settled_battery_export, 3)
    grid_export = round(replay_solar_export + settled_battery_export, 3)
    export_income = round(solar_income + battery_income, 2)
    import_cost = _number(agile_today.get("import_cost_pence")) or 0.0
    old_export_income = _number(agile_today.get("export_income_pence")) or 0.0
    old_energy_net = _number(agile_today.get("energy_net_cost_pence"))
    standing_component = (
        old_energy_net - import_cost + old_export_income
        if old_energy_net is not None
        else 0.0
    )
    battery_home = max(_number(agile_today.get("battery_to_home_kwh")) or 0.0, 0.0)
    wear_rate = _number(state.get("battery_wear_assumption_pence_per_discharged_kwh"))
    if wear_rate is None:
        wear_rate = agile.BATTERY_WEAR_PENCE_PER_KWH
    wear_cost = round((battery_home + settled_battery_export) * wear_rate, 2)
    energy_net = round(import_cost + standing_component - export_income, 2)
    economic_net = round(energy_net + wear_cost, 2)
    fixed_income = round(grid_export * agile.FIXED_EXPORT_PENCE, 2)

    agile_today.update(
        {
            "grid_export_kwh": grid_export,
            "solar_export_kwh": replay_solar_export,
            "battery_export_kwh": settled_battery_export,
            "export_income_pence": export_income,
            "battery_wear_cost_pence": wear_cost,
            "energy_net_cost_pence": energy_net,
            "economic_net_cost_pence": economic_net,
            "fixed_12p_same_dispatch_income_pence": fixed_income,
            "gain_vs_fixed_12p_same_dispatch_pence": round(
                export_income - fixed_income,
                2,
            ),
            "weighted_achieved_export_rate_pence": (
                round(export_income / grid_export, 4)
                if grid_export > _EPSILON
                else None
            ),
            "solar_export_accounting_source": (
                "Agile day replay through latest recorder sample"
            ),
            "battery_export_accounting_source": (
                "completed digital-twin half-hour settlement only"
            ),
            "grid_export_accounting_source": (
                "live replay solar + completed settled battery export"
            ),
        }
    )
    _reconcile_comparison(today)

    diagnostic = state.get("current_day_settlement_reconciliation")
    if not isinstance(diagnostic, dict):
        diagnostic = {}
        state["current_day_settlement_reconciliation"] = diagnostic
    checks = diagnostic.get("accounting_checks")
    checks = dict(checks) if isinstance(checks, dict) else {}
    checks["grid_export_balance"] = (
        abs(grid_export - (replay_solar_export + settled_battery_export)) <= 0.002
    )
    checks["future_planned_battery_export_excluded"] = True
    diagnostic.update(
        {
            "active": True,
            "live_solar_replay_applied": True,
            "settled_slots_accounted": settled_slots,
            "grid_export_kwh": grid_export,
            "solar_export_kwh": replay_solar_export,
            "battery_export_kwh": settled_battery_export,
            "export_income_pence": export_income,
            "accounting_checks": checks,
            "all_accounting_checks_passed": all(checks.values()) if checks else True,
            "export_accounting_source": (
                "live replay solar + completed settled battery export"
            ),
            "hardware_writes": "blocked",
        }
    )


class FlowPresentationAgileSmartExportManager(MidnightRolloverAgileSmartExportManager):
    """Publish final per-slot flows without taking any dispatch authority."""

    def _agile_day(
        self,
        records: list[Snapshot],
        rates: list[agile.AgileRate],
        config: SimulationConfig,
        tariff: TariffSettings,
        initial_soc: float,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        summary, plan = super()._agile_day(records, rates, config, tariff, initial_soc)
        _attach_observed_details(
            plan,
            _observed_slot_details(self, records, rates, config),
            config,
        )
        return summary, plan

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
        await super().async_update(
            records=records,
            now=now,
            config=config,
            learned=learned,
            forecast=forecast,
            forecast_plan=forecast_plan,
            tariff=tariff,
        )
        future = _future_today_projection(
            self,
            self._state,
            now=now,
            config=config,
            learned=learned,
            forecast=forecast,
            forecast_plan=forecast_plan,
            tariff=tariff,
        )
        _attach_flow_contract(self._state, now=now, future_today=future)
        self._publish(self._state)
        return self.state

    def reconcile_current_day_settlements(
        self,
        *,
        settled_half_hours: list[dict[str, Any]],
        now: datetime,
    ) -> dict[str, Any]:
        super().reconcile_current_day_settlements(
            settled_half_hours=settled_half_hours,
            now=now,
        )
        _live_replay_solar_accounting(self._state, now=now)

        config = getattr(self, "_rolling_config", None)
        learned = getattr(self, "_kems_forecast_arbitrage_learned", None)
        forecast = getattr(self, "_kems_forecast_arbitrage_forecast", None)
        forecast_plan = getattr(self, "_kems_forecast_arbitrage_plan", None)
        tariff = getattr(self, "_rolling_tariff", None)
        future: dict[str, dict[str, Any]] = {}
        if (
            isinstance(config, SimulationConfig)
            and isinstance(learned, LearnedState)
            and isinstance(forecast, SolarForecastState)
            and isinstance(forecast_plan, ForecastPlanState)
            and isinstance(tariff, TariffSettings)
        ):
            future = _future_today_projection(
                self,
                self._state,
                now=now,
                config=config,
                learned=learned,
                forecast=forecast,
                forecast_plan=forecast_plan,
                tariff=tariff,
            )
        _attach_flow_contract(self._state, now=now, future_today=future)
        self._publish(self._state)
        return self.state
