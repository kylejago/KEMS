"""Selectable EV charging policy for the KEMS shadow-control contract.

The default policy permits EV charging only in the authoritative configured
23:30-05:30 cheap window. Daytime Intelligent slots and Agile prices do not
widen that window. Optional surplus and disabled modes remain explicit user
choices.

This module changes desired/shadow commands only. It never calls Home Assistant
services or a charger/inverter hardware backend.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from .control import ControlEngine

CONF_EV_CHARGING_POLICY = "ev_charging_policy"
EV_POLICY_SURPLUS = "surplus"
EV_POLICY_CHEAP_WINDOW = "cheap_window"
EV_POLICY_DISABLED = "disabled"
DEFAULT_EV_POLICY = EV_POLICY_CHEAP_WINDOW
EV_POLICY_LABELS = {
    EV_POLICY_SURPLUS: "EV surplus mode",
    EV_POLICY_CHEAP_WINDOW: "EV cheap-window mode",
    EV_POLICY_DISABLED: "EV disabled",
}
EV_POLICY_KEYS = tuple(EV_POLICY_LABELS)
_SURPLUS_THRESHOLD_KW = 0.10


def ev_policy_from_options(options: Mapping[str, Any]) -> str:
    """Return a supported stored policy, defaulting safely to cheap-window."""
    value = str(options.get(CONF_EV_CHARGING_POLICY, DEFAULT_EV_POLICY))
    return value if value in EV_POLICY_KEYS else DEFAULT_EV_POLICY


def configure_ev_charge_policy(
    engine: ControlEngine, options: Mapping[str, Any]
) -> None:
    """Attach one config-entry-specific EV policy to a control engine."""
    engine._kems_ev_charging_policy = ev_policy_from_options(options)


def _surplus_available(snapshot: Any, simulation: Any) -> bool:
    """Return whether simulated PV exceeds non-EV site demand by a safe margin."""
    solar = getattr(simulation, "current_simulated_solar_power_kw", None)
    if solar is None:
        return False
    house = getattr(snapshot, "house_load_kw", None)
    if house is None:
        house = getattr(simulation, "current_simulated_house_load_kw", None)
    if house is None:
        return False
    ev = max(float(getattr(snapshot, "ev_power_kw", 0.0) or 0.0), 0.0)
    non_ev_house = max(float(house) - ev, 0.0)
    return float(solar) - non_ev_house > _SURPLUS_THRESHOLD_KW


def _policy_allows(policy: str, snapshot: Any, simulation: Any, state: Any) -> bool:
    """Return whether the selected shadow policy may allow EV charging now."""
    base_safe = bool(
        state.desired_ev_charging_allowed
        and state.data_fresh
        and state.grid_available
        and not state.island_mode_active
        and not snapshot.saving_session_active
    )
    if not base_safe or policy == EV_POLICY_DISABLED:
        return False
    if policy == EV_POLICY_SURPLUS:
        return bool(snapshot.ev_connected and _surplus_available(snapshot, simulation))
    return bool(snapshot.cheap_period_confirmed)


def _apply_policy(policy: str, snapshot: Any, simulation: Any, state: Any):
    """Apply EV permission and battery-isolation rules to a desired command."""
    allowed = _policy_allows(policy, snapshot, simulation, state)
    if allowed:
        return replace(
            state,
            desired_ev_charging_allowed=True,
            desired_battery_to_home_power_kw=0.0,
            desired_battery_export_power_kw=0.0,
            desired_total_discharge_power_kw=0.0,
            desired_grid_export_allowed=False,
        )

    blocked = replace(state, desired_ev_charging_allowed=False)
    # Outside higher-priority Power Down, if the real charger has not stopped
    # yet, shadow KEMS also isolates the battery until the EV load disappears.
    if snapshot.ev_charging and not snapshot.saving_session_active:
        blocked = replace(
            blocked,
            desired_battery_to_home_power_kw=0.0,
            desired_battery_export_power_kw=0.0,
            desired_total_discharge_power_kw=0.0,
            desired_grid_export_allowed=False,
        )
    return blocked


def install_ev_charge_policy() -> None:
    """Install the per-engine selectable EV policy around the core planner."""
    original = ControlEngine.plan
    if getattr(original, "_kems_ev_charge_policy", False):
        return

    def plan_with_ev_policy(self, snapshot, simulation, now, config):
        # Power Down owns an overlapping overnight slot. The legacy core checks
        # cheap charging first, so remove only that cheap hint for this one call
        # to preserve Safety > Power Down > EV ordering.
        planning_snapshot = snapshot
        if snapshot.saving_session_active and snapshot.cheap_period_confirmed:
            planning_snapshot = replace(snapshot, off_peak=False)
        state = original(self, planning_snapshot, simulation, now, config)
        policy = getattr(self, "_kems_ev_charging_policy", DEFAULT_EV_POLICY)
        return _apply_policy(policy, snapshot, simulation, state)

    plan_with_ev_policy._kems_ev_charge_policy = True
    ControlEngine.plan = plan_with_ev_policy
