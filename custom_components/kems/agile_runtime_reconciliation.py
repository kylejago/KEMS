"""Final canonical reconciliation for Full KEMS Agile shadow planning.

This layer repairs cross-feature hand-offs discovered during real shadow evidence:

* selected rolling slots always carry explicit half-hour bounds so Power Down can
  reserve the actual event periods and preserve the current Agile target;
* a missing *future* Agile price never blocks a known current opportunity or
  reserves battery capacity for the unknown slot;
* an active Power Down routes from the current house load, not the pre-event
  sizing average, and publishes one mutually-exclusive site-meter direction;
* maximum-discharge cannot silently publish a zero export target when the final
  selected current slot still requires export;
* daytime commissioning does not treat a completed off-peak-end timestamp as a
  stale operational tariff input.

All behaviour remains simulation/shadow only.  Nothing in this module enables or
issues Home Assistant, Ohme or FoxESS hardware writes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from . import agile_event_priority_runtime as events
from . import agile_price_horizon_safety_runtime as horizon_runtime
from . import agile_rolling_replan as rolling
from . import commissioning
from .kems_core import SimulationConfig

_EPSILON = 1e-6
_SETTLEMENT_PERIOD = timedelta(minutes=30)


def _slot_bounds_with_default(
    slot: dict[str, Any],
) -> tuple[datetime | None, datetime | None]:
    """Return explicit settlement bounds, inferring the standard 30-minute end."""
    start = events._dt(slot.get("valid_from"))
    end = events._dt(slot.get("valid_to"))
    if start is not None and end is None:
        end = start + _SETTLEMENT_PERIOD
    return start, end


def _normalise_selected_slots(
    plan: dict[str, Any], state: dict[str, Any]
) -> list[dict[str, Any]]:
    """Give every selected rolling allocation an explicit valid-to boundary."""
    by_start: dict[datetime, datetime] = {}
    for raw in state.get("today_slots", []) or []:
        if not isinstance(raw, dict):
            continue
        start = events._dt(raw.get("valid_from"))
        end = events._dt(raw.get("valid_to"))
        if start is not None and end is not None:
            by_start[start] = end

    output: list[dict[str, Any]] = []
    for raw in plan.get("selected_slots", []) or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        start = events._dt(item.get("valid_from"))
        end = events._dt(item.get("valid_to"))
        if start is not None and end is None:
            end = by_start.get(start, start + _SETTLEMENT_PERIOD)
            item["valid_to"] = end.isoformat()
        output.append(item)
    plan["selected_slots"] = output

    next_slot = plan.get("next_export_slot")
    if isinstance(next_slot, dict):
        start = events._dt(next_slot.get("valid_from"))
        if start is not None and events._dt(next_slot.get("valid_to")) is None:
            replacement = next(
                (
                    item
                    for item in output
                    if events._dt(item.get("valid_from")) == start
                ),
                None,
            )
            if replacement is not None:
                plan["next_export_slot"] = dict(replacement)
            else:
                fixed = dict(next_slot)
                fixed["valid_to"] = by_start.get(
                    start, start + _SETTLEMENT_PERIOD
                ).isoformat()
                plan["next_export_slot"] = fixed
    return output


def _current_live_house_kw(self) -> float:
    """Return current house demand for an active event, never a sizing average."""
    snapshot = events._latest_snapshot(self)
    if snapshot is None:
        return 0.0
    value = events._number(getattr(snapshot, "house_load_kw", None))
    if value is None:
        value = events._number(getattr(snapshot, "grid_import_kw", None))
    return max(value or 0.0, 0.0)


def _active_power_down_targets(
    self,
    state: dict[str, Any],
    context: dict[str, Any],
    config: SimulationConfig,
) -> dict[str, Any]:
    """Route an active Power Down from live demand: house first, export second."""
    house = _current_live_house_kw(self)
    solar = events._current_solar_kw(self, config)
    solar_to_home = min(house, solar)
    remaining_house = max(house - solar_to_home, 0.0)

    battery_headroom = min(
        max(config.max_discharge_kw, 0.0),
        max(config.inverter_limit_kw - solar, 0.0),
    )
    soc = rolling._current_agile_soc(state)
    reserve = max(config.battery_reserve_percent, 0.0)
    battery_allowed = soc is None or soc > reserve + 0.05

    battery_to_home = min(remaining_house, battery_headroom) if battery_allowed else 0.0
    remaining_battery_headroom = max(battery_headroom - battery_to_home, 0.0)
    battery_export = (
        min(max(config.export_limit_kw, 0.0), remaining_battery_headroom)
        if battery_allowed
        else 0.0
    )

    solar_surplus = max(solar - solar_to_home, 0.0)
    solar_export = min(
        solar_surplus,
        max(config.export_limit_kw - battery_export, 0.0),
    )
    generation = solar_to_home + solar_export + battery_to_home + battery_export
    site_net = generation - house
    grid_export = min(max(site_net, 0.0), max(config.export_limit_kw, 0.0))
    grid_import = max(-site_net, 0.0)

    # The site boundary has one physical direction at an instant.  Keep the
    # invariant explicit even if future routing inputs acquire rounding noise.
    if grid_import > _EPSILON and grid_export > _EPSILON:
        net = grid_export - grid_import
        grid_export = max(net, 0.0)
        grid_import = max(-net, 0.0)

    total_battery = battery_to_home + battery_export
    total_inverter = min(solar + total_battery, max(config.inverter_limit_kw, 0.0))
    return {
        "mode": "power_down_session",
        "action": "Power Down priority — house first, then maximum safe export",
        "house_battery_kw": round(battery_to_home, 3),
        "battery_export_target_kw": round(battery_export, 3),
        "battery_discharge_target_kw": round(total_battery, 3),
        "battery_charge_target_kw": 0.0,
        "solar_to_home_kw": round(solar_to_home, 3),
        "solar_export_kw": round(solar_export, 3),
        "grid_export_target_kw": round(grid_export, 3),
        "projected_grid_import_kw": round(grid_import, 3),
        "total_inverter_output_kw": round(total_inverter, 3),
        "simulated_soc_percent": soc,
        "minimum_soc_percent": reserve,
        "event_priority": "Power Down > Happy Hour > Agile price",
        "power_down": context,
        "active_house_load_basis": "current_snapshot",
        "site_meter_direction_reconciled": True,
        "hardware_writes": "blocked",
    }


def _nonblocking_price_horizon(
    state: dict[str, Any],
    plan: dict[str, Any],
    horizon: dict[str, Any],
    *,
    now: datetime,
) -> None:
    """Treat unknown future prices as zero-reserved capacity, not a global hold."""
    mode = str(plan.get("dispatch_mode") or "price_optimised")
    current_known = bool(horizon.get("current_slot_known"))
    deadline_override = (
        mode in horizon_runtime._DEADLINE_OVERRIDE_MODES and current_known
    )
    horizon["deadline_override"] = deadline_override

    if horizon.get("complete"):
        return
    if not current_known:
        # Never export when the *current* settlement price itself is unknown.
        _ORIGINAL_HORIZON_HOLD(state, plan, horizon, now=now)
        return

    horizon["battery_export_held"] = False
    horizon["status"] = "incomplete_nonblocking"
    horizon["unknown_price_capacity_reserved_kwh"] = 0.0
    horizon["replan_when_price_publishes"] = True
    horizon["known_prices_remain_dispatchable"] = True
    plan["unknown_price_capacity_reserved_kwh"] = 0.0
    plan["replan_when_price_publishes"] = True


def _restore_required_current_export(
    plan: dict[str, Any], selected: list[dict[str, Any]], now: datetime
) -> None:
    """Prevent a final maximum-discharge plan from silently zeroing its current slot."""
    if str(plan.get("dispatch_mode") or "") != "maximum_discharge":
        return
    current = max(
        events._number(plan.get("current_battery_export_target_kw")) or 0.0, 0.0
    )
    if current > _EPSILON:
        return
    selected_kw = max(events._selected_current_export_kw(selected, now), 0.0)
    if selected_kw <= _EPSILON:
        return
    house_kw = max(events._number(plan.get("current_house_battery_kw")) or 0.0, 0.0)
    plan["current_battery_export_target_kw"] = round(selected_kw, 3)
    plan["current_battery_discharge_target_kw"] = round(house_kw + selected_kw, 3)
    plan["maximum_discharge_zero_target_reconciled"] = True


def _install_rolling_reconciliation() -> None:
    original = rolling._rolling_plan
    if getattr(original, "_kems_runtime_reconciliation", False):
        return

    def rolling_plan_reconciled(self, state, *, now, config, tariff):
        plan = original(self, state, now=now, config=config, tariff=tariff)
        selected = _normalise_selected_slots(plan, state)
        _restore_required_current_export(plan, selected, now)
        plan["settlement_intervals_explicit"] = all(
            events._dt(item.get("valid_from")) is not None
            and events._dt(item.get("valid_to")) is not None
            for item in selected
        )
        return plan

    rolling_plan_reconciled._kems_runtime_reconciliation = True
    rolling._rolling_plan = rolling_plan_reconciled


def _repair_commissioning_tariff_check(payload: dict[str, Any], coordinator) -> None:
    """Ignore completed offpeak_end staleness when the cheap period is not active."""
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return
    snapshot = coordinator.data.snapshot
    stale = set(getattr(snapshot, "tariff_stale_fields", ()) or ())
    if not bool(getattr(snapshot, "cheap_period_confirmed", False)):
        stale.discard("offpeak_end")
    passed = getattr(snapshot, "current_import_rate", None) is not None and not stale
    for check in checks:
        if not isinstance(check, dict) or check.get("key") != "tariff_data":
            continue
        old_status = check.get("status")
        check["status"] = commissioning.PASS if passed else commissioning.FAIL
        check["detail"] = (
            f"Current import {snapshot.current_import_rate} p/kWh; "
            f"cheap period confirmed={snapshot.cheap_period_confirmed}; "
            f"operational stale fields={sorted(stale)}"
        )
        if old_status == check["status"]:
            return
        break
    else:
        return

    required = [item for item in checks if item.get("required")]
    payload["fail_count"] = sum(
        item.get("status") == commissioning.FAIL for item in checks
    )
    payload["wait_count"] = sum(
        item.get("status") == commissioning.WAIT for item in checks
    )
    payload["pass_count"] = sum(
        item.get("status") == commissioning.PASS for item in checks
    )
    required_fail = any(item.get("status") == commissioning.FAIL for item in required)
    required_wait = any(item.get("status") == commissioning.WAIT for item in required)
    foxess_count = int(payload.get("foxess_registered_entity_count") or 0)
    if required_fail:
        state = "Blocked"
    elif not foxess_count:
        state = "Awaiting FoxESS"
    elif required_wait:
        state = "Commissioning"
    else:
        state = "Ready for Shadow"
    payload["state"] = state
    payload["ready_for_shadow"] = state == "Ready for Shadow"


def _install_commissioning_reconciliation() -> None:
    original = commissioning.build_commissioning_snapshot
    if getattr(original, "_kems_runtime_reconciliation", False):
        return

    def build_reconciled(hass, coordinator):
        payload = original(hass, coordinator)
        _repair_commissioning_tariff_check(payload, coordinator)
        payload["tariff_freshness_reconciled"] = True
        return payload

    build_reconciled._kems_runtime_reconciliation = True
    commissioning.build_commissioning_snapshot = build_reconciled


_ORIGINAL_HORIZON_HOLD = horizon_runtime._hold_price_optimised_export


def install_runtime_reconciliation() -> None:
    """Install the final non-versioned Full KEMS Agile reconciliation boundary."""
    events._slot_bounds = _slot_bounds_with_default
    events._active_power_down_targets = _active_power_down_targets
    horizon_runtime._hold_price_optimised_export = _nonblocking_price_horizon
    _install_rolling_reconciliation()
    _install_commissioning_reconciliation()
