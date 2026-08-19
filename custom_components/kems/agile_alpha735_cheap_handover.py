"""Alpha7.35 cheap-window current-routing handover parity.

The Alpha7.30 current-routing card substitutes the live rolling Agile battery
candidate into the proposal digital twin. At the instant the configured
23:30 cheap window opens, that rolling candidate can still represent the final
discharge scan while the core ControlEngine has already changed to Force Charge
and blocked export.

This patch is deliberately reporting-only. During the configured overnight
cheap window it uses the current proposal simulation without substituting a
rolling discharge/export candidate, relabels the active slot as cheap import /
charge, and republishes the live Agile routing attributes. It does not change
optimisation, deadline policy, control commands, safety validation, or hardware
writes.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from . import agile_alpha730_current_routing as routing
from . import agile_smart_export_runtime_base as runtime
from .kems_core import SimulationConfig
from .tariff import TariffSettings, manual_schedule

_LIVE_SENSOR = "sensor.kems_agile_live_scenario"
_ACTION = "cheap overnight period — import / charge; battery export blocked"


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_overnight_cheap(now: datetime, tariff: TariffSettings) -> bool:
    """Use the same configured overnight schedule that authorises control."""
    is_cheap, _, _ = manual_schedule(now, tariff.offpeak_start, tariff.offpeak_end)
    return is_cheap


def _active_slot(state: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """Return the actual settlement slot containing this scan."""
    return routing._current_slot(state, now)


def _cheap_snapshot(self, state: dict[str, Any]) -> dict[str, Any] | None:
    """Build current routing directly from the cheap-period proposal simulation."""
    now = getattr(self, "_rolling_now", None)
    tariff = getattr(self, "_rolling_tariff", None)
    if not isinstance(now, datetime) or not isinstance(tariff, TariffSettings):
        return None
    if not _is_overnight_cheap(now, tariff):
        return None

    current, config, simulation = routing._current_simulation(self, now)
    if (
        current is None
        or not isinstance(config, SimulationConfig)
        or simulation is None
    ):
        return None

    house = max(_number(simulation.current_simulated_house_load_kw) or 0.0, 0.0)
    solar = max(_number(simulation.current_simulated_solar_power_kw) or 0.0, 0.0)
    grid_import = max(_number(simulation.current_simulated_grid_import_kw) or 0.0, 0.0)
    grid_export = max(_number(simulation.current_simulated_grid_export_kw) or 0.0, 0.0)
    solar_to_battery = max(
        _number(simulation.current_simulated_solar_to_battery_power_kw) or 0.0,
        0.0,
    )
    battery_charge = max(
        _number(simulation.current_simulated_battery_charge_power_kw) or 0.0,
        0.0,
    )
    battery_home = max(
        _number(simulation.current_simulated_battery_to_home_power_kw) or 0.0,
        0.0,
    )
    total_ac = max(
        _number(simulation.current_simulated_total_kh7_output_kw) or 0.0,
        0.0,
    )
    total_site_import = _number(simulation.current_simulated_total_site_import_kw)
    if total_site_import is not None:
        grid_import = max(total_site_import, 0.0)

    # The cheap-window simulation is authoritative for current routing. The
    # normal engine already blocks deliberate battery export here; clamp the
    # display as a second reporting guard so a previous rolling candidate can
    # never leak across the boundary.
    battery_export = 0.0
    grid_to_battery = max(battery_charge - solar_to_battery, 0.0)
    solar_export = max(grid_export - battery_export, 0.0)
    solar_ac = max(solar - solar_to_battery - solar_export, 0.0)
    solar_to_home = min(solar_ac, house)

    slot = _active_slot(state, now)
    current_rate = (
        _number(slot.get("rate_pence"))
        if isinstance(slot, dict)
        else _number(state.get("current_rate_pence"))
    )
    live_house = _number(getattr(current, "house_load_kw", None))
    if live_house is None:
        live_house = house

    return {
        "available": True,
        "version": "0.7.0-alpha7.35",
        "generated_at": now.isoformat(),
        "routing_basis": "current coordinator routing snapshot — overnight cheap handover",
        "routing_slot": slot.get("label") if isinstance(slot, dict) else None,
        "routing_valid_from": (
            slot.get("valid_from") if isinstance(slot, dict) else None
        ),
        "routing_valid_to": slot.get("valid_to") if isinstance(slot, dict) else None,
        "routing_action": _ACTION,
        "dispatch_mode": "cheap_charge",
        "current_agile_rate_pence": current_rate,
        "live_house_load_kw": round(max(live_house, 0.0), 3),
        "simulated_house_load_kw": round(house, 3),
        "solar_power_kw": round(solar, 3),
        "grid_import_kw": round(grid_import, 3),
        "grid_export_kw": round(max(solar_export, 0.0), 3),
        "solar_to_home_kw": round(solar_to_home, 3),
        "solar_to_battery_kw": round(solar_to_battery, 3),
        "solar_export_kw": round(solar_export, 3),
        "grid_to_battery_kw": round(grid_to_battery, 3),
        "battery_to_home_kw": round(battery_home, 3),
        "battery_export_kw": 0.0,
        "total_discharge_kw": round(battery_home, 3),
        "normalised_kh7_ac_output_kw": round(total_ac, 3),
        "simulated_soc_percent": _number(simulation.simulated_battery_soc),
        "battery_candidate_basis": (
            "overnight cheap simulation; rolling export candidate suppressed"
        ),
        "solar_routing_basis": "current proposal digital-twin routed AC",
        "reporting_only": True,
        "hardware_writes": "blocked",
    }


def _mark_current_slot_cheap(state: dict[str, Any], now: datetime) -> None:
    """Stop the active cheap slot being rendered as a future export slot."""
    slot = _active_slot(state, now)
    if not isinstance(slot, dict):
        return
    slot["actions"] = ["cheap overnight import / charge"]
    slot["rolling_action"] = _ACTION
    slot["rolling_planned_battery_export_kwh"] = 0.0
    slot["rolling_target_battery_export_kw"] = 0.0


def _publish_with_cheap_handover(self, state: dict[str, Any]) -> None:
    """Republish current Agile routing after all prior Alpha7 patches."""
    alpha735_original_publish(self, state)

    snapshot = _cheap_snapshot(self, state)
    if snapshot is None:
        return

    now = getattr(self, "_rolling_now")
    _mark_current_slot_cheap(state, now)
    state["current_routing_snapshot"] = snapshot
    state["current_action"] = _ACTION

    plan = state.get("rolling_export_plan")
    if isinstance(plan, dict):
        plan["dispatch_mode"] = "cheap_charge"
        plan["dispatch_action"] = _ACTION
        plan["current_battery_export_target_kw"] = 0.0
        plan["current_battery_discharge_target_kw"] = snapshot["total_discharge_kw"]

    live_state = self._hass.states.get(_LIVE_SENSOR)
    attrs = dict(live_state.attributes) if live_state is not None else {}
    attrs.update(
        {
            "current_house_load_kw": snapshot["live_house_load_kw"],
            "live_house_load_kw": snapshot["live_house_load_kw"],
            "simulated_house_load_kw": snapshot["simulated_house_load_kw"],
            "current_solar_power_kw": snapshot["solar_power_kw"],
            "current_grid_import_kw": snapshot["grid_import_kw"],
            "current_grid_export_kw": snapshot["grid_export_kw"],
            "current_solar_to_home_kw": snapshot["solar_to_home_kw"],
            "current_solar_to_battery_kw": snapshot["solar_to_battery_kw"],
            "current_solar_export_kw": snapshot["solar_export_kw"],
            "current_grid_to_battery_kw": snapshot["grid_to_battery_kw"],
            "current_battery_to_home_kw": snapshot["battery_to_home_kw"],
            "current_battery_export_kw": 0.0,
            "battery_discharge_target_kw": snapshot["total_discharge_kw"],
            "battery_export_target_kw": 0.0,
            "routing_basis": snapshot["routing_basis"],
            "routing_slot": snapshot["routing_slot"],
            "routing_valid_from": snapshot["routing_valid_from"],
            "routing_valid_to": snapshot["routing_valid_to"],
            "routing_action": _ACTION,
            "current_action": _ACTION,
            "dispatch_mode": "cheap_charge",
            "current_agile_rate_pence": snapshot["current_agile_rate_pence"],
            "current_routing_snapshot": snapshot,
            "cheap_period_handover_applied": True,
        }
    )
    self._set(
        _LIVE_SENSOR,
        live_state.state if live_state is not None else "Ready",
        attrs,
    )


def install_alpha735_cheap_handover_patch() -> None:
    """Install the reporting-only cheap-window handover exactly once."""
    publish = runtime.EfficientAgileSmartExportManager._publish
    if getattr(publish, "_kems_alpha735_cheap_handover", False):
        return
    global alpha735_original_publish
    alpha735_original_publish = publish
    _publish_with_cheap_handover._kems_alpha735_cheap_handover = True
    runtime.EfficientAgileSmartExportManager._publish = _publish_with_cheap_handover
