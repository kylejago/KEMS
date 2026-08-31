"""Canonical Intelligent-dispatch transition replanning.

A confirmed daytime Octopus Intelligent dispatch is an authoritative cheap
period. The preserved Alpha7.35 handover intentionally recognises only the
configured overnight schedule, so a later rolling-target reconciliation can
otherwise reapply a stale discharge/export command after ControlEngine has
already selected confirmed cheap charging.

Alpha8.64 keeps the frozen Alpha7 boundary intact and closes that authority gap:

* the active confirmed Intelligent slot is removed from the rolling export
  candidate set before the plan is rebuilt;
* current routing is handed over to the already-calculated cheap-period digital
  twin so Grid supplies the home, battery export/discharge are blocked, and the
  canonical charge target is visible to control/shadow alignment; and
* confirmed-start and confirmed-end transitions are recorded explicitly. The
  normal rolling path then recalculates from the latest settled/current SOC on
  the first coordinator scan that observes either transition.

This remains simulation/shadow only. It does not enable hardware writes.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from . import agile_alpha730_current_routing as routing
from . import agile_rolling_replan as rolling
from .agile_deadline_settlement_consistency import (
    DeadlineSettlementConsistencyAgileSmartExportManager,
)
from .kems_core import SimulationConfig, Snapshot
from .tariff import TariffSettings, manual_schedule

_ACTION = "confirmed Intelligent dispatch — import / charge; battery export blocked"
_SLOT_ACTION = "confirmed Intelligent dispatch — cheap import / charge"
_LIVE_SENSOR = "sensor.kems_agile_live_scenario"
_PLAN_SENSOR = "sensor.kems_agile_rolling_export_plan"
_REPLAN_SENSOR = "sensor.kems_intelligent_dispatch_replan"
_EPSILON = 1e-6

_ORIGINAL_ROLLING_PLAN = None


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _confirmed_intelligent_dispatch(
    snapshot: Snapshot | Any,
    *,
    now: datetime,
    tariff: TariffSettings,
) -> bool:
    """Return true only for a fail-closed daytime Intelligent cheap dispatch."""
    if snapshot is None:
        return False

    overnight, _, _ = manual_schedule(now, tariff.offpeak_start, tariff.offpeak_end)
    if overnight:
        return False

    stale = tuple(getattr(snapshot, "tariff_stale_fields", ()) or ())
    evidence = getattr(snapshot, "intelligent_slot_evidence", None)
    evidence = evidence if isinstance(evidence, dict) else {}
    confirmation = str(
        getattr(snapshot, "intelligent_slot_confirmation", "") or ""
    ).lower()
    return bool(
        getattr(snapshot, "intelligent_slot", None) is True
        and "intelligent_slot" not in stale
        and getattr(snapshot, "ev_charging", None) is True
        and confirmation == "confirmed"
        and evidence.get("confirmed") is True
        and evidence.get("large_import_permitted") is True
    )


def _latest_snapshot(records: list[Snapshot] | Any) -> Snapshot | Any | None:
    """Return the newest record supplied to the rolling manager."""
    if not isinstance(records, list) or not records:
        return None
    return records[-1]


def _current_slot(state: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """Return the settlement slot containing this coordinator scan."""
    return routing._current_slot(state, now)


def _filtered_dispatch_state(
    state: dict[str, Any],
    *,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Exclude the active dispatch slot from rolling export allocation."""
    active = _current_slot(state, now)
    slots = state.get("today_slots")
    if not isinstance(active, dict) or not isinstance(slots, list):
        return state, active

    filtered = dict(state)
    # Keep the original future slot dictionaries so the canonical planner still
    # writes its recalculated allocations back to the published rows. Only the
    # active dispatch slot is withheld from export capacity.
    filtered["today_slots"] = [slot for slot in slots if slot is not active]
    return filtered, active


def _rolling_plan_with_intelligent_dispatch(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Rebuild the remaining plan without spending the active dispatch slot."""
    assert _ORIGINAL_ROLLING_PLAN is not None
    snapshot = getattr(self, "_alpha864_current_snapshot", None)
    if not _confirmed_intelligent_dispatch(snapshot, now=now, tariff=tariff):
        return _ORIGINAL_ROLLING_PLAN(
            self,
            state,
            now=now,
            config=config,
            tariff=tariff,
        )

    filtered, active = _filtered_dispatch_state(state, now=now)
    plan = _ORIGINAL_ROLLING_PLAN(
        self,
        filtered,
        now=now,
        config=config,
        tariff=tariff,
    )
    if not isinstance(plan, dict):
        return plan

    plan["intelligent_dispatch_slot_excluded_from_export_plan"] = bool(active)
    plan["intelligent_dispatch_replan_reason"] = getattr(
        self,
        "_alpha864_transition",
        "confirmed_active",
    )
    if isinstance(active, dict):
        plan["intelligent_dispatch_slot"] = {
            "valid_from": active.get("valid_from"),
            "valid_to": active.get("valid_to"),
            "label": active.get("label"),
        }
    return plan


def install_intelligent_dispatch_replan() -> None:
    """Install the canonical rolling-plan exclusion after Alpha7/Alpha8 wrappers."""
    global _ORIGINAL_ROLLING_PLAN
    current = rolling._rolling_plan
    if getattr(current, "_kems_intelligent_dispatch_replan", False):
        return
    _ORIGINAL_ROLLING_PLAN = current
    _rolling_plan_with_intelligent_dispatch._kems_intelligent_dispatch_replan = True
    rolling._rolling_plan = _rolling_plan_with_intelligent_dispatch


def _cheap_snapshot(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any] | None:
    """Build authoritative current routing from the confirmed-cheap simulation."""
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
    total_ac = max(
        _number(simulation.current_simulated_total_kh7_output_kw) or 0.0,
        0.0,
    )
    total_site_import = _number(simulation.current_simulated_total_site_import_kw)
    if total_site_import is not None:
        grid_import = max(total_site_import, 0.0)

    # Confirmed cheap import is authoritative: Grid supplies the house while
    # battery discharge/export are blocked. The existing Alpha8.58 simulation
    # already routes PV to battery first and exports only remaining PV.
    grid_to_battery = max(battery_charge - solar_to_battery, 0.0)
    solar_export = max(grid_export, 0.0)
    solar_ac_after_charge = max(solar - solar_to_battery - solar_export, 0.0)
    solar_to_home = min(solar_ac_after_charge, house)

    slot = _current_slot(state, now)
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
        "version": "0.8.0-alpha8.64",
        "generated_at": now.isoformat(),
        "routing_basis": "current routing snapshot — confirmed Intelligent dispatch",
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
        "grid_export_kw": round(solar_export, 3),
        "solar_to_home_kw": round(solar_to_home, 3),
        "solar_to_battery_kw": round(solar_to_battery, 3),
        "solar_export_kw": round(solar_export, 3),
        "grid_to_battery_kw": round(grid_to_battery, 3),
        "battery_to_home_kw": 0.0,
        "battery_export_kw": 0.0,
        "total_discharge_kw": 0.0,
        "normalised_kh7_ac_output_kw": round(total_ac, 3),
        "simulated_soc_percent": _number(simulation.simulated_battery_soc),
        "battery_candidate_basis": (
            "confirmed Intelligent cheap simulation; rolling export candidate "
            "suppressed"
        ),
        "solar_routing_basis": "current proposal digital-twin routed AC",
        "reporting_only": True,
        "hardware_writes": "blocked",
    }


def _mark_current_slot_cheap(state: dict[str, Any], *, now: datetime) -> None:
    """Make the active row agree with confirmed Intelligent cheap authority."""
    slot = _current_slot(state, now)
    if not isinstance(slot, dict):
        return
    slot["actions"] = [_SLOT_ACTION]
    slot["rolling_action"] = _ACTION
    slot["rolling_planned_battery_export_kwh"] = 0.0
    slot["rolling_target_battery_export_kw"] = 0.0
    slot["rolling_target_total_discharge_kw"] = 0.0
    slot["intelligent_dispatch_replanned"] = True


def _apply_intelligent_dispatch_handover(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any] | None:
    """Make current routing and rolling command agree with confirmed cheap."""
    snapshot = _cheap_snapshot(self, state, now=now)
    if snapshot is None:
        return None

    _mark_current_slot_cheap(state, now=now)
    state["current_routing_snapshot"] = snapshot
    state["current_action"] = _ACTION

    plan = state.get("rolling_export_plan")
    if isinstance(plan, dict):
        plan["dispatch_mode"] = "cheap_charge"
        plan["dispatch_action"] = _ACTION
        plan["current_house_battery_kw"] = 0.0
        plan["current_battery_export_target_kw"] = 0.0
        plan["current_battery_discharge_target_kw"] = 0.0
        plan["current_battery_charge_target_kw"] = round(
            snapshot["solar_to_battery_kw"] + snapshot["grid_to_battery_kw"],
            3,
        )
        plan["intelligent_dispatch_replan_applied"] = True
        plan["intelligent_dispatch_current_slot_export_blocked"] = True

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
            "current_battery_to_home_kw": 0.0,
            "current_battery_export_kw": 0.0,
            "battery_discharge_target_kw": 0.0,
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
            "intelligent_dispatch_handover_applied": True,
        }
    )
    self._set(
        _LIVE_SENSOR,
        live_state.state if live_state is not None else "Ready",
        attrs,
    )
    return snapshot


def _transition_diagnostic(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    active: bool,
) -> dict[str, Any]:
    """Publish explicit evidence that dispatch start/end caused a fresh plan."""
    plan = state.get("rolling_export_plan")
    plan = plan if isinstance(plan, dict) else {}
    current_soc = _number(plan.get("simulated_soc_percent"))
    previous_soc = _number(getattr(self, "_alpha864_previous_plan_soc", None))
    transition = str(getattr(self, "_alpha864_transition", "inactive") or "inactive")
    diagnostic = {
        "active": active,
        "transition": transition,
        "generated_at": now.isoformat(),
        "previous_confirmed": bool(
            getattr(self, "_alpha864_previous_confirmed_for_scan", False)
        ),
        "confirmed": bool(getattr(self, "_alpha864_confirmed_for_scan", False)),
        "previous_plan_soc_percent": (
            round(previous_soc, 3) if previous_soc is not None else None
        ),
        "replanned_soc_percent": (
            round(current_soc, 3) if current_soc is not None else None
        ),
        "plan_invalidated": transition in {"confirmed_start", "confirmed_end"},
        "replan_completed": True,
        "current_slot_export_blocked": active,
        "replan_policy": (
            "rebuild on confirmed Intelligent start/end and every coordinator scan"
        ),
        "hardware_writes": "blocked",
    }
    state["intelligent_dispatch_replan"] = diagnostic
    return diagnostic


def _republish_plan_sensor(self, state: dict[str, Any]) -> None:
    """Refresh the rolling-plan entity after the canonical handover mutation."""
    plan = state.get("rolling_export_plan")
    if not isinstance(plan, dict):
        return
    selected = plan.get("selected_slots")
    selected = selected if isinstance(selected, list) else []
    self._set(
        _PLAN_SENSOR,
        (
            f"{len(selected)} slots · "
            f"{float(plan.get('planned_battery_export_kwh') or 0.0):.2f} kWh"
            if plan.get("available")
            else "Unavailable"
        ),
        {
            "friendly_name": "Agile rolling battery export plan",
            "mode": "simulation_only",
            **plan,
        },
    )


class IntelligentDispatchReplanAgileSmartExportManager(
    DeadlineSettlementConsistencyAgileSmartExportManager
):
    """Own confirmed Intelligent start/end replanning after all prior owners."""

    async def async_update(
        self,
        *,
        records,
        now: datetime,
        config: SimulationConfig,
        learned,
        forecast,
        forecast_plan,
        tariff: TariffSettings,
    ) -> dict[str, Any]:
        current = _latest_snapshot(records)
        confirmed = _confirmed_intelligent_dispatch(current, now=now, tariff=tariff)
        previous = bool(getattr(self, "_alpha864_previous_confirmed", False))
        if confirmed and not previous:
            transition = "confirmed_start"
        elif previous and not confirmed:
            transition = "confirmed_end"
        elif confirmed:
            transition = "confirmed_active"
        else:
            transition = "inactive"

        previous_plan = getattr(self, "_state", {}).get("rolling_export_plan", {})
        previous_plan = previous_plan if isinstance(previous_plan, dict) else {}
        self._alpha864_previous_plan_soc = _number(
            previous_plan.get("simulated_soc_percent")
        )
        self._alpha864_current_snapshot = current
        self._alpha864_previous_confirmed_for_scan = previous
        self._alpha864_confirmed_for_scan = confirmed
        self._alpha864_transition = transition

        result = await super().async_update(
            records=records,
            now=now,
            config=config,
            learned=learned,
            forecast=forecast,
            forecast_plan=forecast_plan,
            tariff=tariff,
        )
        self._alpha864_previous_confirmed = confirmed
        return result

    def _publish(self, state: dict[str, Any]) -> None:
        super()._publish(state)
        now = getattr(self, "_rolling_now", None)
        tariff = getattr(self, "_rolling_tariff", None)
        if not isinstance(now, datetime) or not isinstance(tariff, TariffSettings):
            return

        current = getattr(self, "_alpha864_current_snapshot", None)
        active = _confirmed_intelligent_dispatch(current, now=now, tariff=tariff)
        if active:
            _apply_intelligent_dispatch_handover(self, state, now=now)
        diagnostic = _transition_diagnostic(self, state, now=now, active=active)
        _republish_plan_sensor(self, state)
        self._set(
            _REPLAN_SENSOR,
            str(diagnostic["transition"]),
            {
                "friendly_name": "Intelligent dispatch rolling replan",
                **diagnostic,
            },
        )
