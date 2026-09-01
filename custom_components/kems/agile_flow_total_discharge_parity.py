"""Keep future Today flow presentation in rolling total-discharge parity.

The rolling total-discharge ledger already owns the final house-first/export split
for future Agile slots.  This reporting owner runs after dispatch observability
and mirrors that proven split into the customer-facing ``flow_*`` contract before
reusing the existing displayed-SOC continuity rebase.

This module is reporting-only.  It does not re-run or alter the optimiser,
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


def _reconcile_future_total_discharge_flow(state: dict[str, Any]) -> int:
    """Mirror strict-future rolling house/export allocations into ``flow_*``.

    The active half-hour remains owned by canonical current routing.  Only later
    rows with an explicit, internally balanced total-discharge ledger are
    eligible.  Planner fields are never changed; this mutates presentation fields
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


class TotalDischargeFlowParityAgileSmartExportManager(
    IntelligentDispatchObservabilityAgileSmartExportManager
):
    """Publish future flow/SOC from the final rolling total-discharge split."""

    def _publish(self, state: dict[str, Any]) -> None:
        _reconcile_future_total_discharge_flow(state)
        config = getattr(self, "_rolling_config", None)
        routing = state.get("current_routing_snapshot")
        routing = routing if isinstance(routing, dict) else {}
        now = _dt(routing.get("generated_at"))
        if isinstance(config, SimulationConfig) and now is not None:
            _rebase_display_soc(state, now=now, config=config)
        super()._publish(state)
