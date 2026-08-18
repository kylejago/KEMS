"""Alpha 7.17 live deadline saturation for Agile Smart Export.

When the 10% cheap-window target becomes physically unreachable, KEMS stops
preserving battery energy for later prices and uses the full safe battery
discharge path. House demand remains first priority and deliberate battery
export receives the remaining inverter/export headroom.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_rolling_replan as rolling
from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from .agile_deadline_dispatch import _effective_deadline_kw, _target_percent
from .kems_core import SimulationConfig
from .tariff import TariffSettings

_EPSILON = 1e-6
_LIVE_SENSOR = "sensor.kems_agile_live_scenario"
_ROLLING_SENSOR = "sensor.kems_agile_rolling_export_plan"


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _deadline_context(
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Describe the live deadline pressure from the latest simulated SOC."""
    soc = rolling._current_agile_soc(state)
    effective_kw = _effective_deadline_kw(config)
    target_soc = _target_percent(config)
    capacity = max(config.battery_capacity_kwh, 0.1)
    efficiency = max(config.discharge_efficiency, 0.01)
    deadline = agile._next_cheap(now, tariff).astimezone(UTC)
    now_utc = now.astimezone(UTC)
    hours = max((deadline - now_utc).total_seconds() / 3600.0, 0.0)

    if soc is None or effective_kw <= _EPSILON or hours <= _EPSILON:
        return {
            "available": False,
            "mode": "unavailable",
            "soc_percent": soc,
            "target_soc_percent": target_soc,
            "effective_discharge_kw": effective_kw,
            "deadline": deadline.isoformat(),
        }

    battery_kwh = capacity * min(max(soc, 0.0), 100.0) / 100.0
    target_kwh = capacity * target_soc / 100.0
    required_ac = max(battery_kwh - target_kwh, 0.0) * efficiency
    remaining_ac = effective_kw * hours
    margin = remaining_ac - required_ac
    required_average_kw = required_ac / hours if hours > _EPSILON else None

    if required_ac <= 0.01:
        mode = "target_reached"
    elif margin < -0.05:
        mode = "maximum_discharge"
    elif margin <= max(effective_kw * 0.5, 0.25):
        mode = "deadline_following"
    else:
        mode = "price_optimised"

    return {
        "available": True,
        "mode": mode,
        "soc_percent": round(soc, 2),
        "target_soc_percent": round(target_soc, 1),
        "effective_discharge_kw": round(effective_kw, 3),
        "required_discharge_kwh": round(required_ac, 3),
        "remaining_capacity_kwh": round(remaining_ac, 3),
        "deadline_margin_kwh": round(margin, 3),
        "required_average_kw": (
            round(required_average_kw, 3) if required_average_kw is not None else None
        ),
        "deadline": deadline.isoformat(),
    }


def _remaining_current_slot_hours(state: dict[str, Any], now: datetime) -> float:
    """Return the remaining duration of the active Agile half-hour."""
    now_utc = now.astimezone(UTC)
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        try:
            start = datetime.fromisoformat(str(slot["valid_from"])).astimezone(UTC)
            end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
        except (KeyError, TypeError, ValueError):
            continue
        if start <= now_utc < end:
            return max((end - now_utc).total_seconds() / 3600.0, 0.0)
    return 0.0


def _current_slot(state: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """Return the active Agile slot."""
    now_utc = now.astimezone(UTC)
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        try:
            start = datetime.fromisoformat(str(slot["valid_from"])).astimezone(UTC)
            end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
        except (KeyError, TypeError, ValueError):
            continue
        if start <= now_utc < end:
            return slot
    return None


def _dispatch_targets(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Calculate the battery discharge/export target for the current scan."""
    context = _deadline_context(state, now=now, config=config, tariff=tariff)
    if not context.get("available"):
        return context

    effective_kw = float(context.get("effective_discharge_kw") or 0.0)
    house_kw = min(max(rolling._current_house_headroom_kw(self, config), 0.0), effective_kw)
    remaining_hours = _remaining_current_slot_hours(state, now)
    current_slot = _current_slot(state, now)
    planned_kwh = (
        _number(current_slot.get("rolling_planned_battery_export_kwh"))
        if isinstance(current_slot, dict)
        else None
    )
    planned_export_kw = (
        min(max((planned_kwh or 0.0) / remaining_hours, 0.0), effective_kw)
        if remaining_hours > _EPSILON
        else 0.0
    )

    mode = str(context.get("mode") or "price_optimised")
    required_average = float(context.get("required_average_kw") or 0.0)
    if mode == "maximum_discharge":
        total_target_kw = effective_kw
        action = "maximum discharge — 10% target physically unreachable; house first"
    elif mode == "deadline_following":
        total_target_kw = min(
            max(required_average, house_kw + planned_export_kw),
            effective_kw,
        )
        action = "deadline-following discharge — protect 10% target; house first"
    elif mode == "target_reached":
        total_target_kw = min(house_kw, effective_kw)
        action = "10% target reached — no deliberate battery export"
    else:
        total_target_kw = min(house_kw + planned_export_kw, effective_kw)
        action = "price-optimised rolling export; house first"

    export_target_kw = min(
        max(total_target_kw - house_kw, 0.0),
        max(config.export_limit_kw, 0.0),
        max(config.inverter_limit_kw - house_kw, 0.0),
        max(config.max_discharge_kw - house_kw, 0.0),
    )
    return {
        **context,
        "house_battery_kw": round(house_kw, 3),
        "planned_price_export_kw": round(planned_export_kw, 3),
        "battery_discharge_target_kw": round(total_target_kw, 3),
        "battery_export_target_kw": round(export_target_kw, 3),
        "action": action,
    }


def _elapsed_routing_attributes(state: dict[str, Any]) -> dict[str, Any]:
    """Calculate current-slot power using elapsed time, not a full half-hour."""
    generated_at = state.get("generated_at")
    try:
        now = datetime.fromisoformat(str(generated_at)).astimezone(UTC)
    except (TypeError, ValueError):
        return {}

    slot = _current_slot(state, now)
    if slot is None:
        return {}
    try:
        start = datetime.fromisoformat(str(slot["valid_from"])).astimezone(UTC)
        end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
    except (KeyError, TypeError, ValueError):
        return {}

    full_hours = max((end - start).total_seconds() / 3600.0, 0.0)
    elapsed_hours = min(
        max((now - start).total_seconds() / 3600.0, 0.0),
        full_hours,
    )
    if elapsed_hours <= _EPSILON:
        return {}

    def power(name: str) -> float | None:
        value = _number(slot.get(name))
        return None if value is None else round(max(value / elapsed_hours, 0.0), 3)

    return {
        "routing_basis": "current simulated half-hour — elapsed-slot average",
        "routing_elapsed_hours": round(elapsed_hours, 4),
        "current_house_load_kw": power("house_load_kwh"),
        "current_solar_power_kw": power("solar_generation_kwh"),
        "current_grid_import_kw": power("grid_import_kwh"),
        "current_grid_export_kw": power("grid_export_kwh"),
        "current_solar_to_home_kw": power("solar_to_home_kwh"),
        "current_solar_to_battery_kw": power("solar_to_battery_kwh"),
        "current_solar_export_kw": power("solar_export_kwh"),
        "current_grid_to_battery_kw": power("grid_to_battery_kwh"),
        "current_battery_to_home_kw": power("battery_to_home_kwh"),
        "current_battery_export_kw": power("battery_export_kwh"),
    }


def install_alpha717_dispatch_patch() -> None:
    """Install maximum-discharge fallback and current-scan target reporting."""
    original_floor = agile.AgileSmartExportManager._floor
    if not getattr(original_floor, "_kems_alpha717", False):

        def floor_with_alpha717(
            self,
            records,
            index,
            current,
            config,
            reserve,
            capacity,
        ):
            if getattr(self, "_kems_alpha717_force_max_discharge", False):
                target = capacity * _target_percent(config) / 100.0
                return min(max(reserve, target), capacity)
            return original_floor(
                self,
                records,
                index,
                current,
                config,
                reserve,
                capacity,
            )

        floor_with_alpha717._kems_alpha717 = True
        agile.AgileSmartExportManager._floor = floor_with_alpha717

    original_update = runtime.EfficientAgileSmartExportManager.async_update
    if not getattr(original_update, "_kems_alpha717", False):

        async def update_with_alpha717(
            self,
            *,
            records,
            now,
            config,
            learned,
            forecast,
            forecast_plan,
            tariff,
        ):
            context = _deadline_context(
                self._state,
                now=now,
                config=config,
                tariff=tariff,
            )
            self._kems_alpha717_force_max_discharge = (
                context.get("mode") == "maximum_discharge"
            )
            result = await original_update(
                self,
                records=records,
                now=now,
                config=config,
                learned=learned,
                forecast=forecast,
                forecast_plan=forecast_plan,
                tariff=tariff,
            )
            return result

        update_with_alpha717._kems_alpha717 = True
        runtime.EfficientAgileSmartExportManager.async_update = update_with_alpha717

    original_rolling_plan = rolling._rolling_plan
    if not getattr(original_rolling_plan, "_kems_alpha717", False):

        def rolling_plan_with_alpha717(
            self,
            state,
            *,
            now,
            config,
            tariff,
        ):
            plan = original_rolling_plan(
                self,
                state,
                now=now,
                config=config,
                tariff=tariff,
            )
            targets = _dispatch_targets(
                self,
                state,
                plan,
                now=now,
                config=config,
                tariff=tariff,
            )
            plan.update(
                {
                    "dispatch_mode": targets.get("mode"),
                    "dispatch_action": targets.get("action"),
                    "current_house_battery_kw": targets.get("house_battery_kw"),
                    "current_battery_discharge_target_kw": targets.get(
                        "battery_discharge_target_kw"
                    ),
                    "current_battery_export_target_kw": targets.get(
                        "battery_export_target_kw"
                    ),
                    "required_average_discharge_kw": targets.get(
                        "required_average_kw"
                    ),
                    "live_deadline_margin_kwh": targets.get("deadline_margin_kwh"),
                }
            )

            slot = _current_slot(state, now)
            remaining_hours = _remaining_current_slot_hours(state, now)
            export_target = _number(targets.get("battery_export_target_kw"))
            if slot is not None and export_target is not None:
                slot["rolling_target_battery_export_kw"] = round(export_target, 3)
                slot["rolling_target_total_discharge_kw"] = targets.get(
                    "battery_discharge_target_kw"
                )
                slot["rolling_action"] = targets.get("action")
                slot["rolling_planned_battery_export_kwh"] = round(
                    export_target * remaining_hours,
                    3,
                )

            if targets.get("mode") == "maximum_discharge":
                now_utc = now.astimezone(UTC)
                for future in state.get("today_slots", []):
                    if not isinstance(future, dict):
                        continue
                    try:
                        end = datetime.fromisoformat(str(future["valid_to"])).astimezone(
                            UTC
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
                    if end <= now_utc:
                        continue
                    future["rolling_action"] = (
                        "maximum discharge — target unreachable; house first"
                    )
                    future["actions"] = [
                        "maximum discharge — target unreachable; house first"
                    ]
                state["current_action"] = targets.get("action")
            elif targets.get("mode") == "deadline_following":
                state["current_action"] = targets.get("action")
            return plan

        rolling_plan_with_alpha717._kems_alpha717 = True
        rolling._rolling_plan = rolling_plan_with_alpha717

    original_publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(original_publish, "_kems_alpha717", False):

        def publish_with_alpha717(self, state: dict[str, Any]) -> None:
            original_publish(self, state)
            elapsed = _elapsed_routing_attributes(state)
            live_state = self._hass.states.get(_LIVE_SENSOR)
            attrs = dict(live_state.attributes) if live_state is not None else {}
            if elapsed:
                attrs.update(elapsed)

            rolling_state = self._hass.states.get(_ROLLING_SENSOR)
            plan = dict(rolling_state.attributes) if rolling_state is not None else {}
            mode = str(plan.get("dispatch_mode") or "unavailable")
            target_total = _number(plan.get("current_battery_discharge_target_kw"))
            target_export = _number(plan.get("current_battery_export_target_kw"))
            historical_battery_export = _number(attrs.get("current_battery_export_kw"))
            historical_grid_export = _number(attrs.get("current_grid_export_kw"))

            if target_export is not None:
                attrs["simulated_elapsed_battery_export_kw"] = historical_battery_export
                attrs["simulated_elapsed_grid_export_kw"] = historical_grid_export
                attrs["current_battery_export_kw"] = round(target_export, 3)
                solar_export = _number(attrs.get("current_solar_export_kw")) or 0.0
                if mode == "maximum_discharge":
                    solar_export = 0.0
                    attrs["current_solar_export_kw"] = 0.0
                attrs["current_grid_export_kw"] = round(target_export + solar_export, 3)
                attrs["routing_basis"] = "rolling target — current coordinator scan"
                attrs["routing_action"] = plan.get("dispatch_action")
                attrs["dispatch_mode"] = mode
                attrs["battery_discharge_target_kw"] = target_total
                attrs["battery_export_target_kw"] = target_export
                attrs["required_average_discharge_kw"] = plan.get(
                    "required_average_discharge_kw"
                )
                attrs["deadline_margin_kwh"] = plan.get("live_deadline_margin_kwh")

            self._set(
                _LIVE_SENSOR,
                live_state.state if live_state is not None else "Ready",
                attrs,
            )

            simulated_total = None
            battery_home = _number(attrs.get("current_battery_to_home_kw"))
            simulated_export = _number(attrs.get("simulated_elapsed_battery_export_kw"))
            if battery_home is not None or simulated_export is not None:
                simulated_total = (battery_home or 0.0) + (simulated_export or 0.0)
            shortfall = (
                max(target_total - simulated_total, 0.0)
                if target_total is not None and simulated_total is not None
                else None
            )

            for entity_id, value, name, unit in (
                (
                    "sensor.kems_agile_dispatch_mode",
                    mode,
                    "Agile live dispatch mode",
                    None,
                ),
                (
                    "sensor.kems_agile_battery_discharge_target_now",
                    target_total,
                    "Agile battery discharge target now",
                    "kW",
                ),
                (
                    "sensor.kems_agile_battery_export_target_now",
                    target_export,
                    "Agile battery export target now",
                    "kW",
                ),
                (
                    "sensor.kems_agile_dispatch_shortfall_now",
                    shortfall,
                    "Agile simulated discharge shortfall vs target",
                    "kW",
                ),
            ):
                attributes = {"friendly_name": name, "mode": "simulation_only"}
                if unit is not None:
                    attributes["unit_of_measurement"] = unit
                self._set(entity_id, agile._state(value), attributes)

        publish_with_alpha717._kems_alpha717 = True
        runtime.EfficientAgileSmartExportManager._publish = publish_with_alpha717
