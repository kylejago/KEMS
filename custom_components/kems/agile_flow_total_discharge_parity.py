"""Keep Today flow presentation in canonical battery-energy parity.

The rolling total-discharge ledger already owns the final house-first/export split
for future Agile slots. This reporting owner mirrors that proven split into the
customer-facing ``flow_*`` contract, reuses the established active/future SOC
continuity rebase, and then backcasts completed-row display SOC from the settled
current battery state through the battery energy that KEMS already displays.

This module is reporting-only. It does not re-run or alter the optimiser,
dispatch, Power Down, cheap charging, safety, or hardware writes.
"""

from __future__ import annotations

from typing import Any

from .agile_intelligent_dispatch_observability import (
    IntelligentDispatchObservabilityAgileSmartExportManager,
)
from .agile_live_solar_soc_continuity import _dt, _number, _rebase_display_soc
from .kems_core import SimulationConfig
from .kems_core.slot_flow import build_slot_flow

_EPSILON = 1e-6
_LEDGER_TOLERANCE_KWH = 0.01
_FLOW_TOLERANCE_KWH = 0.0005
_BACKCAST_ENERGY_TOLERANCE_KWH = 0.05
_BOUNDARY_SOC_TOLERANCE_PERCENT = 0.25


def _reconcile_future_total_discharge_flow(state: dict[str, Any]) -> int:
    """Mirror strict-future rolling house/export allocations into ``flow_*``.

    The active half-hour remains owned by canonical current routing. Only later
    rows with an explicit, internally balanced total-discharge ledger are
    eligible. Planner fields are never changed; this mutates presentation fields
    only and lets the established SOC-continuity owner consume the corrected
    displayed battery deltas.
    """
    routing = state.get("current_routing_snapshot")
    if not isinstance(routing, dict) or not routing.get("available"):
        return 0
    future_boundary = _dt(routing.get("routing_valid_to"))
    generated_at = _dt(routing.get("generated_at"))
    if future_boundary is None:
        return 0

    corrected = 0
    eligible = 0
    slots = state.get("today_slots")
    if not isinstance(slots, list):
        return 0

    for slot in slots:
        if not isinstance(slot, dict):
            continue
        start = _dt(slot.get("valid_from"))
        if start is None or start < future_boundary:
            continue

        planned_total = _number(slot.get("planned_total_battery_discharge_kwh"))
        planned_home = _number(slot.get("planned_battery_to_home_kwh"))
        planned_export = _number(slot.get("rolling_planned_battery_export_kwh"))
        if planned_total is None or planned_home is None or planned_export is None:
            continue

        planned_total = max(planned_total, 0.0)
        planned_home = max(planned_home, 0.0)
        planned_export = max(planned_export, 0.0)
        if abs(planned_total - (planned_home + planned_export)) > _LEDGER_TOLERANCE_KWH:
            continue
        eligible += 1

        flow_home = max(_number(slot.get("flow_battery_to_home_kwh")) or 0.0, 0.0)
        flow_export = max(_number(slot.get("flow_battery_export_kwh")) or 0.0, 0.0)
        flow_discharge = flow_home + flow_export
        if (
            abs(flow_home - planned_home) <= _FLOW_TOLERANCE_KWH
            and abs(flow_export - planned_export) <= _FLOW_TOLERANCE_KWH
            and abs(flow_discharge - planned_total) <= _LEDGER_TOLERANCE_KWH
        ):
            continue

        values = build_slot_flow(
            grid_import_kwh=_number(slot.get("flow_grid_import_kwh")),
            solar_generation_kwh=_number(slot.get("flow_solar_kwh")),
            solar_to_home_kwh=_number(slot.get("flow_solar_to_home_kwh")),
            solar_to_battery_kwh=_number(slot.get("flow_solar_to_battery_kwh")),
            solar_export_kwh=_number(slot.get("flow_solar_export_kwh")),
            grid_to_battery_kwh=_number(slot.get("flow_grid_to_battery_kwh")),
            battery_to_home_kwh=planned_home,
            battery_export_kwh=planned_export,
            estimated_soc_percent=_number(slot.get("flow_estimated_soc_percent")),
            basis=str(
                slot.get("flow_basis") or "KEMS forecast + final rolling allocation"
            ),
            scope=str(slot.get("flow_scope") or "full slot"),
        )
        slot.update(values)
        slot["flow_total_discharge_parity_applied"] = True
        slot["flow_total_discharge_parity_source"] = "rolling total-discharge ledger"
        slot["flow_total_discharge_parity_hardware_writes"] = "blocked"
        corrected += 1

    state["flow_total_discharge_parity"] = {
        "active": True,
        "generated_at": generated_at.isoformat() if generated_at is not None else None,
        "future_boundary": future_boundary.isoformat(),
        "eligible_rows": eligible,
        "corrected_rows": corrected,
        "basis": "rolling planned home + export = planned total discharge",
        "active_row_owner": "canonical current routing",
        "reporting_only": True,
        "hardware_writes": "blocked",
    }
    return corrected


def _active_elapsed_battery_delta_kwh(
    slot: dict[str, Any],
    config: SimulationConfig,
) -> float | None:
    """Return stored-battery change already elapsed inside the active slot.

    Active ``flow_*`` values describe the *remaining* part of the half-hour, so
    they cannot reconstruct its start. The legacy/replay fields on the manager
    row still describe elapsed activity through the latest recorder sample.
    Battery export is therefore derived from elapsed Grid export less elapsed
    solar export; ``battery_export_kwh`` itself may already hold the remaining
    rolling target.
    """
    fields = {
        "grid_export": _number(slot.get("grid_export_kwh")),
        "solar_export": _number(slot.get("solar_export_kwh")),
        "battery_home": _number(slot.get("battery_to_home_kwh")),
        "solar_charge": _number(slot.get("solar_to_battery_kwh")),
        "grid_charge": _number(slot.get("grid_to_battery_kwh")),
    }
    if any(value is None for value in fields.values()):
        return None

    efficiency = max(float(config.discharge_efficiency), _EPSILON)
    elapsed_export = max(fields["grid_export"] - fields["solar_export"], 0.0)
    elapsed_discharge = max(fields["battery_home"], 0.0) + elapsed_export
    elapsed_charge = max(fields["solar_charge"], 0.0) + max(
        fields["grid_charge"], 0.0
    )
    return elapsed_charge - (elapsed_discharge / efficiency)


def _completed_display_battery_delta_kwh(
    slot: dict[str, Any],
    config: SimulationConfig,
) -> float | None:
    """Return one completed row's stored-battery delta from canonical flow."""
    charge = _number(slot.get("flow_battery_charge_kwh"))
    home = _number(slot.get("flow_battery_to_home_kwh"))
    export = _number(slot.get("flow_battery_export_kwh"))
    if charge is None or home is None or export is None:
        return None
    if slot.get("actions") == ["future slot"]:
        return None
    efficiency = max(float(config.discharge_efficiency), _EPSILON)
    return max(charge, 0.0) - ((max(home, 0.0) + max(export, 0.0)) / efficiency)


def _maximum_full_slot_soc_swing_percent(config: SimulationConfig) -> float | None:
    """Return a conservative physical half-hour SOC movement limit."""
    capacity = float(config.battery_capacity_kwh)
    if capacity <= _EPSILON:
        return None
    discharge_efficiency = max(float(config.discharge_efficiency), _EPSILON)
    charge_efficiency = max(float(config.charge_efficiency), _EPSILON)
    discharge_kw = max(float(config.max_discharge_kw), 0.0)
    charge_kw = max(float(config.max_charge_kw), 0.0)
    discharge_stored_kwh = discharge_kw * 0.5 / discharge_efficiency
    charge_stored_kwh = charge_kw * 0.5 * charge_efficiency
    return max(discharge_stored_kwh, charge_stored_kwh) / capacity * 100.0


def _settled_rollover_seed_soc(state: dict[str, Any], active: dict[str, Any]) -> float | None:
    """Return the persisted SOC seed for this local day when it still matches."""
    continuity = state.get("midnight_replay_continuity")
    continuity = continuity if isinstance(continuity, dict) else {}
    seed = continuity.get("settled_rollover_seed")
    if not isinstance(seed, dict):
        return None
    local_date = str(active.get("local_from") or "")[:10]
    if local_date and str(seed.get("target_date") or "") != local_date:
        return None
    return _number(seed.get("agile_midnight_soc_percent"))


def _reconcile_completed_settled_soc(
    state: dict[str, Any],
    *,
    now: Any,
    config: SimulationConfig,
) -> int:
    """Backcast completed display SOC from the settled current battery state.

    Alpha8.39 already settles the authoritative current-day SOC from executed
    battery export. Completed half-hour rows, however, historically retained the
    older replay SOC while the active/future rows used that settled authority.
    This reporting-only backcast anchors on the same current SOC, removes the
    battery energy already elapsed in the active slot to recover its start, then
    walks completed canonical flow backwards. Accounting/optimiser fields are
    deliberately untouched.
    """
    routing = state.get("current_routing_snapshot")
    if not isinstance(routing, dict) or not routing.get("available"):
        return 0
    current_soc = _number(routing.get("simulated_soc_percent"))
    active_start = _dt(routing.get("routing_valid_from"))
    active_end = _dt(routing.get("routing_valid_to"))
    generated_at = _dt(routing.get("generated_at")) or _dt(now)
    capacity = float(config.battery_capacity_kwh)
    if (
        current_soc is None
        or active_start is None
        or active_end is None
        or generated_at is None
        or active_end <= active_start
        or capacity <= _EPSILON
    ):
        return 0

    slots = [
        slot for slot in state.get("today_slots", []) or [] if isinstance(slot, dict)
    ]
    slots.sort(key=lambda slot: _dt(slot.get("valid_from")) or active_end)
    active_index = next(
        (
            index
            for index, slot in enumerate(slots)
            if _dt(slot.get("valid_from")) == active_start
            and _dt(slot.get("valid_to")) == active_end
        ),
        None,
    )
    if active_index is None:
        return 0

    active = slots[active_index]
    elapsed_delta = _active_elapsed_battery_delta_kwh(active, config)
    if elapsed_delta is None:
        state["completed_flow_soc_continuity"] = {
            "active": True,
            "applied": False,
            "reason": "active elapsed battery energy unavailable",
            "generated_at": generated_at.isoformat(),
            "reporting_only": True,
            "hardware_writes": "blocked",
        }
        return 0

    current_kwh = min(max(current_soc, 0.0), 100.0) * capacity / 100.0
    boundary_kwh = current_kwh - elapsed_delta
    if (
        boundary_kwh < -_BACKCAST_ENERGY_TOLERANCE_KWH
        or boundary_kwh > capacity + _BACKCAST_ENERGY_TOLERANCE_KWH
    ):
        state["completed_flow_soc_continuity"] = {
            "active": True,
            "applied": False,
            "reason": "active-slot backcast falls outside battery capacity",
            "generated_at": generated_at.isoformat(),
            "current_soc_percent": round(current_soc, 3),
            "reporting_only": True,
            "hardware_writes": "blocked",
        }
        return 0
    boundary_kwh = min(max(boundary_kwh, 0.0), capacity)
    active_start_soc = 100.0 * boundary_kwh / capacity

    latest_completed_pre = None
    if active_index > 0:
        latest_completed_pre = _number(
            slots[active_index - 1].get("flow_estimated_soc_percent")
        )
    active_projected_end = _number(active.get("flow_estimated_soc_percent"))

    expected_end = active_start
    corrected = 0
    earliest_label = None
    latest_label = None
    reached_day_start = True
    for slot in reversed(slots[:active_index]):
        start = _dt(slot.get("valid_from"))
        end = _dt(slot.get("valid_to"))
        if start is None or end is None or end != expected_end:
            reached_day_start = False
            break
        delta = _completed_display_battery_delta_kwh(slot, config)
        if delta is None:
            reached_day_start = False
            break
        prior_boundary = boundary_kwh - delta
        if (
            prior_boundary < -_BACKCAST_ENERGY_TOLERANCE_KWH
            or prior_boundary > capacity + _BACKCAST_ENERGY_TOLERANCE_KWH
        ):
            reached_day_start = False
            break

        old_soc = _number(slot.get("flow_estimated_soc_percent"))
        slot.setdefault("flow_soc_pre_settlement_backcast_percent", old_soc)
        slot["flow_estimated_soc_percent"] = round(
            100.0 * boundary_kwh / capacity,
            1,
        )
        slot["flow_settled_soc_backcast_applied"] = True
        slot["flow_settled_soc_backcast_source"] = (
            "settled current SOC + active elapsed battery energy + completed flow"
        )
        slot["flow_settled_soc_backcast_hardware_writes"] = "blocked"
        label = str(slot.get("label") or "") or None
        latest_label = latest_label or label
        earliest_label = label
        corrected += 1

        boundary_kwh = min(max(prior_boundary, 0.0), capacity)
        expected_end = start

    if corrected != active_index:
        reached_day_start = False

    latest_completed_rebased = None
    if active_index > 0 and corrected:
        latest_completed_rebased = _number(
            slots[active_index - 1].get("flow_estimated_soc_percent")
        )
    maximum_swing = _maximum_full_slot_soc_swing_percent(config)
    pre_jump = (
        abs(latest_completed_pre - active_projected_end)
        if latest_completed_pre is not None and active_projected_end is not None
        else None
    )
    corrected_jump = (
        abs(latest_completed_rebased - active_projected_end)
        if latest_completed_rebased is not None and active_projected_end is not None
        else None
    )
    boundary_physically_possible = (
        corrected_jump <= maximum_swing + _BOUNDARY_SOC_TOLERANCE_PERCENT
        if corrected_jump is not None and maximum_swing is not None
        else None
    )

    reconstructed_day_start_soc = (
        round(100.0 * boundary_kwh / capacity, 3) if reached_day_start else None
    )
    rollover_seed_soc = _settled_rollover_seed_soc(state, active)
    rollover_residual = (
        round(reconstructed_day_start_soc - rollover_seed_soc, 3)
        if reconstructed_day_start_soc is not None and rollover_seed_soc is not None
        else None
    )

    state["completed_flow_soc_continuity"] = {
        "active": True,
        "applied": corrected > 0,
        "generated_at": generated_at.isoformat(),
        "current_soc_percent": round(current_soc, 3),
        "active_start_soc_percent": round(active_start_soc, 3),
        "active_projected_end_soc_percent": active_projected_end,
        "completed_rows_rebased": corrected,
        "earliest_rebased_label": earliest_label,
        "latest_rebased_label": latest_label,
        "latest_completed_pre_backcast_soc_percent": latest_completed_pre,
        "latest_completed_rebased_soc_percent": latest_completed_rebased,
        "pre_backcast_boundary_jump_percent": (
            round(pre_jump, 3) if pre_jump is not None else None
        ),
        "rebased_boundary_jump_percent": (
            round(corrected_jump, 3) if corrected_jump is not None else None
        ),
        "maximum_full_slot_soc_swing_percent": (
            round(maximum_swing, 3) if maximum_swing is not None else None
        ),
        "boundary_physically_possible": boundary_physically_possible,
        "reached_day_start": reached_day_start,
        "reconstructed_day_start_soc_percent": reconstructed_day_start_soc,
        "rollover_seed_soc_percent": rollover_seed_soc,
        "rollover_residual_percent": rollover_residual,
        "basis": (
            "settled current SOC backcast through elapsed active and completed "
            "displayed battery energy"
        ),
        "completed_row_owner": "settled display continuity",
        "active_row_owner": "canonical current routing",
        "future_row_owner": "rolling total-discharge + canonical SOC continuity",
        "reporting_only": True,
        "hardware_writes": "blocked",
    }
    return corrected


class TotalDischargeFlowParityAgileSmartExportManager(
    IntelligentDispatchObservabilityAgileSmartExportManager
):
    """Publish completed/current/future flow SOC from one physical authority."""

    def _publish(self, state: dict[str, Any]) -> None:
        _reconcile_future_total_discharge_flow(state)
        config = getattr(self, "_rolling_config", None)
        routing = state.get("current_routing_snapshot")
        routing = routing if isinstance(routing, dict) else {}
        now = _dt(routing.get("generated_at"))
        if isinstance(config, SimulationConfig) and now is not None:
            _rebase_display_soc(state, now=now, config=config)
            _reconcile_completed_settled_soc(state, now=now, config=config)
        super()._publish(state)
