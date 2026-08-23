"""Canonical overnight-only EV charging policy for KEMS shadow control.

The EV is permitted to charge only during the authoritative configured overnight
cheap window. Daytime Intelligent slots, Agile prices and normal solar/export
optimisation never widen that window. Power Down remains higher priority.

This module changes desired/shadow commands only. It does not call Home Assistant
services and it does not write to Ohme, FoxESS or any other hardware backend.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .control import ControlEngine


def _ev_allowed(snapshot: Any, state: Any) -> bool:
    """Return whether the desired EV command may permit charging now."""
    return bool(
        snapshot.cheap_period_confirmed
        and not snapshot.saving_session_active
        and state.desired_ev_charging_allowed
        and state.data_fresh
        and state.grid_available
        and not state.island_mode_active
    )


def _apply_ev_policy(snapshot: Any, state: Any):
    """Apply the overnight EV gate and prevent battery energy feeding the EV."""
    allowed = _ev_allowed(snapshot, state)
    if not allowed:
        return replace(state, desired_ev_charging_allowed=False)
    return replace(
        state,
        desired_ev_charging_allowed=True,
        desired_battery_to_home_power_kw=0.0,
        desired_battery_export_power_kw=0.0,
        desired_total_discharge_power_kw=0.0,
        desired_grid_export_allowed=False,
    )


def install_ev_charge_policy() -> None:
    """Install the EV policy once around the hardware-independent planner."""
    original = ControlEngine.plan
    if getattr(original, "_kems_ev_charge_policy", False):
        return

    def plan_with_ev_policy(self, snapshot, simulation, now, config):
        state = original(self, snapshot, simulation, now, config)
        return _apply_ev_policy(snapshot, state)

    plan_with_ev_policy._kems_ev_charge_policy = True
    ControlEngine.plan = plan_with_ev_policy
