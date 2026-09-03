"""Final Full KEMS Agile dispatch reconciliation.

The Alpha7-derived Agile planner remains the economic authority.  This layer fixes
post-plan parity only:

* manual Weekend Happy Hour is replayed as a temporary free import/charge window
  so the day ledger, rolling SOC and later Agile decisions share one battery state;
* current charge routing is finalised from the Full KEMS Agile plan rather than a
  second generic proposal reconstruction;
* the Agile shadow command carries the same charge target as the optimiser;
* completed Happy Hour planning auto-clears while retaining one completed-event
  record for same-day/history replay evidence.

The 100% charge target is deliberately unchanged. Reserve diagnostics are sourced
from the final rolling plan so the 15% planning target, 10% absolute safety floor
and 12% recovery threshold cannot drift into a second hard-coded policy copy.
This module remains simulation/shadow only and cannot enable hardware writes.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from . import agile_cheap_window_handover_runtime as cheap
from . import agile_current_routing_runtime as routing
from . import agile_event_priority_runtime as events
from . import agile_shadow_command_runtime as shadow
from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from .happy_hour import (
    CONF_HAPPY_HOUR_ENABLED,
    CONF_HAPPY_HOUR_START,
    HAPPY_HOUR_FAIR_USE_KWH_PER_REWARD,
    happy_hour_duration_hours,
    parse_happy_hour_start,
)
from .kems_core import SimulationConfig
from .runtime_options import async_set_runtime_options

_EPSILON = 1e-6
_LAST_COMPLETED_START = "weekend_happy_hour_last_completed_start"
_LAST_COMPLETED_END = "weekend_happy_hour_last_completed_end"
_LAST_COMPLETED_DURATION = "weekend_happy_hour_last_completed_duration_hours"

_EVENT_DIRECT_GRAPH_IDS = frozenset(
    {
        "sensor.kems_agile_simulated_house_load_power",
        "sensor.kems_agile_simulated_solar_power",
        "sensor.kems_agile_simulated_battery_net_power",
        "sensor.kems_agile_simulated_grid_import_power",
        "sensor.kems_agile_simulated_grid_export_power",
    }
)


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _entry(self):
    """Return the manager config entry when the event layer recorded its id."""
    entry_id = getattr(self, "_kems_alpha743_entry_id", None)
    if not entry_id:
        return None
    return self._hass.config_entries.async_get_entry(str(entry_id))


def _options(self) -> dict[str, Any]:
    entry = _entry(self)
    return dict(entry.options) if entry is not None else {}


def _completed_event(options: dict[str, Any]) -> dict[str, Any] | None:
    """Return the retained completed Happy Hour, if one exists."""
    start = parse_happy_hour_start(options.get(_LAST_COMPLETED_START))
    if start is None:
        return None
    end = parse_happy_hour_start(options.get(_LAST_COMPLETED_END))
    try:
        duration = int(options.get(_LAST_COMPLETED_DURATION, 1))
    except (TypeError, ValueError):
        duration = 1
    duration = 2 if duration >= 2 else 1
    if end is None or end <= start:
        end = start + timedelta(hours=duration)
    return {
        "enabled": True,
        "source": "manual_completed",
        "start": start,
        "end": end,
        "duration_hours": duration,
        "fair_use_cap_kwh": HAPPY_HOUR_FAIR_USE_KWH_PER_REWARD * duration,
        "planning_auto_cleared": True,
    }


def _event_for_replay_day(self, day: date) -> dict[str, Any] | None:
    """Return the live or last completed event matching one replay day."""
    options = _options(self)
    if bool(options.get(CONF_HAPPY_HOUR_ENABLED, False)):
        start = parse_happy_hour_start(options.get(CONF_HAPPY_HOUR_START))
        if start is not None and start.astimezone(agile.LONDON).date() == day:
            duration = happy_hour_duration_hours(options)
            return {
                "enabled": True,
                "source": "manual",
                "start": start,
                "end": start + timedelta(hours=duration),
                "duration_hours": duration,
                "fair_use_cap_kwh": HAPPY_HOUR_FAIR_USE_KWH_PER_REWARD * duration,
            }
    completed = _completed_event(options)
    if (
        completed is not None
        and completed["start"].astimezone(agile.LONDON).date() == day
    ):
        return completed
    return None


def _power_down_active(snapshot, moment: datetime) -> bool:
    """Return whether a joined Power Down overlaps this replay instant."""
    if not bool(getattr(snapshot, "saving_session_joined", False)):
        return False
    start = events._dt(getattr(snapshot, "saving_session_start", None))
    end = events._dt(getattr(snapshot, "saving_session_end", None))
    current = moment.astimezone(UTC)
    return bool(start is not None and end is not None and start <= current < end)


def _happy_hour_replay_records(self, records: list[Any]) -> list[Any]:
    """Project a manual Happy Hour as a free charge window in the Agile replay.

    Only replay copies are changed.  The authoritative tariff schedule and the
    original KEMS observations remain untouched, so Intelligent daytime slots
    cannot become control-authoritative cheap periods.
    """
    if not records:
        return records
    day = records[0].timestamp.astimezone(agile.LONDON).date()
    event = _event_for_replay_day(self, day)
    if event is None:
        return records

    start = event["start"].astimezone(UTC)
    end = event["end"].astimezone(UTC)
    projected: list[Any] = []
    for snapshot in records:
        moment = snapshot.timestamp.astimezone(UTC)
        if start <= moment < end and not _power_down_active(snapshot, moment):
            projected.append(
                replace(
                    snapshot,
                    off_peak=True,
                    intelligent_slot=False,
                    current_import_rate=0.0,
                    next_import_rate=0.0,
                    forecast_maximum_overnight_soc_percent=100.0,
                )
            )
        else:
            projected.append(snapshot)
    return projected


def _install_replay_reconciliation() -> None:
    """Make the core Agile day ledger account for Happy Hour exactly once."""
    method = agile.AgileSmartExportManager._agile_day
    if getattr(method, "_kems_dispatch_reconciliation", False):
        return
    original = method

    def agile_day_with_happy_hour(
        self,
        records,
        rates,
        config,
        tariff,
        initial_soc,
    ):
        projected = _happy_hour_replay_records(self, list(records))
        summary, plan = original(
            self,
            projected,
            rates,
            config,
            tariff,
            initial_soc,
        )
        event = (
            _event_for_replay_day(
                self,
                projected[0].timestamp.astimezone(agile.LONDON).date(),
            )
            if projected
            else None
        )
        if event is not None:
            summary = dict(summary)
            summary.update(
                {
                    "happy_hour_reconciled": True,
                    "happy_hour_source": event.get("source"),
                    "happy_hour_start": event["start"].isoformat(),
                    "happy_hour_end": event["end"].isoformat(),
                    "happy_hour_fair_use_cap_kwh": event.get("fair_use_cap_kwh"),
                    "happy_hour_import_price_pence": 0.0,
                }
            )
        return summary, plan

    agile_day_with_happy_hour._kems_dispatch_reconciliation = True
    agile.AgileSmartExportManager._agile_day = agile_day_with_happy_hour


def _current_soc(state: dict[str, Any]) -> float | None:
    """Return the authoritative Agile replay SOC for the current day."""
    return events._base_soc(state)


def _charge_route(
    self,
    state: dict[str, Any],
    base: dict[str, Any],
    *,
    charge_target_kw: float,
    dispatch_mode: str,
    action: str,
) -> dict[str, Any]:
    """Return one mutually exclusive site-meter route for a charging dispatch."""
    config = getattr(self, "_rolling_config", None)
    if not isinstance(config, SimulationConfig):
        return base

    house = max(
        _number(base.get("simulated_house_load_kw"))
        or _number(base.get("live_house_load_kw"))
        or 0.0,
        0.0,
    )
    solar = max(_number(base.get("solar_power_kw")) or 0.0, 0.0)
    soc = _current_soc(state)
    if soc is None:
        soc = _number(base.get("simulated_soc_percent"))

    charge = min(
        max(charge_target_kw, 0.0),
        max(config.max_charge_kw, 0.0),
        max(config.inverter_limit_kw, 0.0),
    )
    if soc is not None and soc >= 99.95:
        charge = 0.0

    # A physical site meter has one net direction at an instant.  Use solar
    # locally before requesting grid energy; only true surplus remains export.
    solar_to_home = min(solar, house)
    remaining_house = max(house - solar_to_home, 0.0)
    remaining_solar = max(solar - solar_to_home, 0.0)
    solar_to_battery = min(remaining_solar, charge)
    grid_to_battery = max(charge - solar_to_battery, 0.0)

    if config.site_import_limit_kw is not None:
        safe_grid_charge = max(
            float(config.site_import_limit_kw) - remaining_house,
            0.0,
        )
        grid_to_battery = min(grid_to_battery, safe_grid_charge)
        charge = solar_to_battery + grid_to_battery

    solar_export = min(
        max(remaining_solar - solar_to_battery, 0.0),
        max(config.export_limit_kw, 0.0),
        max(config.inverter_limit_kw - solar_to_home, 0.0),
    )
    grid_import = remaining_house + grid_to_battery
    grid_export = solar_export

    result = dict(base)
    result.update(
        {
            "available": True,
            "routing_basis": "final Full KEMS Agile dispatch reconciliation",
            "routing_action": action,
            "dispatch_mode": dispatch_mode,
            "simulated_house_load_kw": round(house, 3),
            "solar_power_kw": round(solar, 3),
            "grid_import_kw": round(grid_import, 3),
            "grid_export_kw": round(grid_export, 3),
            "solar_to_home_kw": round(solar_to_home, 3),
            "solar_to_battery_kw": round(solar_to_battery, 3),
            "solar_export_kw": round(solar_export, 3),
            "grid_to_battery_kw": round(grid_to_battery, 3),
            "battery_to_home_kw": 0.0,
            "battery_export_kw": 0.0,
            "total_discharge_kw": 0.0,
            "normalised_kh7_ac_output_kw": round(
                solar_to_home + solar_export,
                3,
            ),
            "simulated_soc_percent": soc,
            "battery_candidate_basis": "exact final Full KEMS Agile charge target",
            "site_meter_direction_reconciled": True,
            "reporting_only": True,
            "hardware_writes": "blocked",
        }
    )
    return result


def _install_current_routing_reconciliation() -> None:
    """Make current routing consume the final Agile charge target."""
    snapshot = routing._snapshot
    if not getattr(snapshot, "_kems_dispatch_reconciliation", False):
        original_snapshot = snapshot

        def snapshot_with_charge(self, state):
            base = original_snapshot(self, state)
            if not isinstance(base, dict) or not base.get("available"):
                return base
            plan = state.get("rolling_export_plan")
            plan = plan if isinstance(plan, dict) else {}
            mode = str(plan.get("dispatch_mode") or base.get("dispatch_mode") or "")
            if mode != "happy_hour_charge":
                return base
            charge = max(
                _number(plan.get("current_battery_charge_target_kw")) or 0.0,
                0.0,
            )
            return _charge_route(
                self,
                state,
                base,
                charge_target_kw=charge,
                dispatch_mode="happy_hour_charge",
                action="Weekend Happy Hour — maximum safe free-grid charge",
            )

        snapshot_with_charge._kems_dispatch_reconciliation = True
        routing._snapshot = snapshot_with_charge

    cheap_snapshot = cheap._cheap_snapshot
    if getattr(cheap_snapshot, "_kems_dispatch_reconciliation", False):
        return
    original_cheap_snapshot = cheap_snapshot

    def cheap_snapshot_with_charge(self, state):
        base = original_cheap_snapshot(self, state)
        if not isinstance(base, dict) or not base.get("available"):
            return base
        config = getattr(self, "_rolling_config", None)
        if not isinstance(config, SimulationConfig):
            return base
        soc = _current_soc(state)
        charge = (
            0.0
            if soc is not None and soc >= 99.95
            else min(
                max(config.max_charge_kw, 0.0),
                max(config.inverter_limit_kw, 0.0),
            )
        )
        plan = state.get("rolling_export_plan")
        if isinstance(plan, dict):
            plan["current_battery_charge_target_kw"] = round(charge, 3)
            plan["charge_target_soc_percent"] = 100.0
        return _charge_route(
            self,
            state,
            base,
            charge_target_kw=charge,
            dispatch_mode="cheap_charge",
            action="cheap overnight period — import / charge; battery export blocked",
        )

    cheap_snapshot_with_charge._kems_dispatch_reconciliation = True
    cheap._cheap_snapshot = cheap_snapshot_with_charge


def _install_shadow_charge_parity() -> None:
    """Copy the final Agile charge target into the independent shadow command."""
    builder = shadow.build_agile_shadow_command
    if getattr(builder, "_kems_dispatch_reconciliation", False):
        return
    original_builder = builder

    def build_with_charge(control, simulation, config, agile_state):
        candidate, context = original_builder(
            control,
            simulation,
            config,
            agile_state,
        )
        if candidate is None:
            return candidate, context

        plan = agile_state.get("rolling_export_plan")
        plan = plan if isinstance(plan, dict) else {}
        mode = str(plan.get("dispatch_mode") or "")
        charge = _number(plan.get("current_battery_charge_target_kw"))
        if charge is None and mode == "cheap_charge":
            charge = _number(getattr(control, "desired_charge_power_kw", None))
        charge = max(charge or 0.0, 0.0)

        candidate = replace(
            candidate,
            desired_work_mode=(
                "Force Charge" if charge > _EPSILON else candidate.desired_work_mode
            ),
            desired_charge_power_kw=round(charge, 3),
        )
        context = dict(context)
        target = dict(context.get("optimizer_target") or {})
        target["charge_kw"] = round(charge, 3)
        parity = dict(context.get("parity") or {})
        parity["charge_target_matches_optimizer"] = (
            abs(candidate.desired_charge_power_kw - charge) <= 0.001
        )
        context.update(
            {
                "optimizer_target": target,
                "parity": parity,
                "parity_passed": all(parity.values()),
                "charge_target_kw": round(charge, 3),
                "charge_target_source": (
                    "Full KEMS Agile rolling plan"
                    if plan.get("current_battery_charge_target_kw") is not None
                    else "core confirmed-cheap control target"
                ),
            }
        )
        return candidate, context

    build_with_charge._kems_dispatch_reconciliation = True
    shadow.build_agile_shadow_command = build_with_charge


async def _auto_clear_completed_event(self, happy: dict[str, Any]) -> None:
    """Persist completion evidence and switch manual planning off atomically."""
    entry = _entry(self)
    if entry is None:
        return
    start = str(happy.get("start") or "")
    end = str(happy.get("end") or "")
    duration = int(_number(happy.get("duration_hours")) or 1)
    await async_set_runtime_options(
        self._hass,
        entry,
        {
            CONF_HAPPY_HOUR_ENABLED: False,
            _LAST_COMPLETED_START: start,
            _LAST_COMPLETED_END: end,
            _LAST_COMPLETED_DURATION: duration,
        },
    )


def _schedule_completed_event_auto_clear(
    self,
    happy: dict[str, Any],
) -> None:
    """Schedule one post-publish auto-clear after the booked slot has ended."""
    if (
        str(happy.get("mode") or "") != "complete"
        or not bool(_options(self).get(CONF_HAPPY_HOUR_ENABLED, False))
        or getattr(self, "_kems_happy_hour_auto_clear_pending", False)
    ):
        return
    self._kems_happy_hour_auto_clear_pending = True
    self._hass.async_create_task(_auto_clear_completed_event(self, happy))


def _install_completed_event_fallback() -> None:
    """Let the just-completed event remain replay evidence after auto-clear."""
    getter = events._happy_hour_event
    if getattr(getter, "_kems_dispatch_reconciliation", False):
        return
    original_getter = getter

    def event_with_completed_fallback(self):
        live = original_getter(self)
        if live.get("enabled"):
            return live
        completed = _completed_event(_options(self))
        if completed is None:
            return live
        now = getattr(self, "_rolling_now", None)
        if not isinstance(now, datetime):
            return live
        if (
            completed["start"].astimezone(agile.LONDON).date()
            != now.astimezone(agile.LONDON).date()
        ):
            return live
        return completed

    event_with_completed_fallback._kems_dispatch_reconciliation = True
    events._happy_hour_event = event_with_completed_fallback

    # Happy Hour is now part of the core Agile replay, so the old Alpha7.43
    # post-publish SOC overlay would double-count the free charge.
    corrected = events._corrected_happy_hour_soc
    if not getattr(corrected, "_kems_dispatch_reconciliation", False):

        def replay_owned_happy_hour_soc(
            self,
            state,
            context,
            *,
            now,
            config,
            power_down,
        ):
            return None

        replay_owned_happy_hour_soc._kems_dispatch_reconciliation = True
        events._corrected_happy_hour_soc = replay_owned_happy_hour_soc


def _install_publish_reconciliation() -> None:
    """Suppress the obsolete event graph overlay and auto-clear completed input."""
    manager = runtime.EfficientAgileSmartExportManager

    setter = manager._set
    if not getattr(setter, "_kems_dispatch_reconciliation", False):
        original_set = setter

        def set_with_graph_owner(self, entity_id, value, attributes):
            if (
                getattr(self, "_kems_suppress_event_graph_overlay", False)
                and entity_id in _EVENT_DIRECT_GRAPH_IDS
            ):
                return
            original_set(self, entity_id, value, attributes)

        set_with_graph_owner._kems_dispatch_reconciliation = True
        manager._set = set_with_graph_owner

    publish = manager._publish
    if getattr(publish, "_kems_dispatch_reconciliation", False):
        return
    original_publish = publish

    def publish_with_reconciliation(self, state):
        now = getattr(self, "_rolling_now", None)
        config = getattr(self, "_rolling_config", None)
        tariff = getattr(self, "_rolling_tariff", None)
        charging = False
        if (
            isinstance(now, datetime)
            and isinstance(config, SimulationConfig)
            and tariff is not None
        ):
            power_down = events._power_down_context(
                self,
                now=now,
                config=config,
                tariff=tariff,
            )
            happy = events._happy_hour_context(
                self,
                state,
                now=now,
                config=config,
                tariff=tariff,
                power_down=power_down,
            )
            charging = str(
                happy.get("mode") or ""
            ) == "charging" and not power_down.get("active")
        self._kems_suppress_event_graph_overlay = charging
        try:
            original_publish(self, state)
        finally:
            self._kems_suppress_event_graph_overlay = False

        happy = state.get("happy_hour_plan")
        if isinstance(happy, dict):
            _schedule_completed_event_auto_clear(self, happy)

        rolling_plan = state.get("rolling_export_plan")
        rolling_plan = rolling_plan if isinstance(rolling_plan, dict) else {}
        planning_target = _number(rolling_plan.get("planning_target_soc_percent"))
        if planning_target is None:
            planning_target = _number(rolling_plan.get("target_soc_percent"))
        if planning_target is None and isinstance(config, SimulationConfig):
            planning_target = _number(config.battery_reserve_percent)

        state["dispatch_reconciliation"] = {
            "available": True,
            "happy_hour_replay_owner": "Agile day ledger",
            "current_routing_owner": "final Full KEMS Agile dispatch",
            "shadow_charge_parity": True,
            "happy_hour_planning_auto_clear": True,
            "charge_target_soc_percent": 100.0,
            "planning_target_soc_percent": planning_target,
            "hard_safety_floor_soc_percent": _number(
                rolling_plan.get("hard_safety_floor_soc_percent")
            ),
            "hard_safety_recovery_soc_percent": _number(
                rolling_plan.get("hard_safety_recovery_soc_percent")
            ),
            "reserve_hierarchy_source": "final rolling_export_plan",
            "hardware_writes": "blocked",
        }

    publish_with_reconciliation._kems_dispatch_reconciliation = True
    manager._publish = publish_with_reconciliation


def install_dispatch_reconciliation() -> None:
    """Install the final Full KEMS Agile output-reconciliation boundary."""
    _install_replay_reconciliation()
    _install_current_routing_reconciliation()
    _install_shadow_charge_parity()
    _install_completed_event_fallback()
    _install_publish_reconciliation()
