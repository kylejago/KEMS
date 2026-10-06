"""Continuous Today -> Tomorrow SOC presentation for KEMS Agile plans.

Alpha9.82 closes a customer-visible midnight discontinuity where the Today table
could finish from the canonical rolling SOC path while Tomorrow was still
displayed from an independently seeded forecast replay.  Tomorrow now inherits
the final displayed Today SOC at the exact local-day boundary and advances
sequentially through the energy already published for each Tomorrow slot.

This is deliberately a final presentation owner.  It does not re-run the
optimiser, change dispatch, alter Power Down priority, or grant any FoxESS
hardware-write authority.
"""

from __future__ import annotations

import math
from typing import Any

from .agile_live_solar_soc_continuity import _dt
from .kems_core import SimulationConfig
from .kems_core.slot_flow import build_slot_flow

_EPSILON = 1e-6


def _number(value: Any) -> float | None:
    """Return one finite float when available."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _non_negative(*values: Any) -> float:
    """Return the first finite non-negative energy value."""
    for value in values:
        number = _number(value)
        if number is not None:
            return max(number, 0.0)
    return 0.0


def _today_midnight_soc(state: dict[str, Any]) -> tuple[float | None, str | None]:
    """Return the final Today SOC exactly before Tomorrow starts."""
    tomorrow = [
        item
        for item in state.get("tomorrow_slots", []) or []
        if isinstance(item, dict)
    ]
    if not tomorrow:
        return None, None
    starts = [_dt(item.get("valid_from")) for item in tomorrow]
    starts = [item for item in starts if item is not None]
    if not starts:
        return None, None
    tomorrow_start = min(starts)

    candidate: dict[str, Any] | None = None
    candidate_end = None
    for slot in state.get("today_slots", []) or []:
        if not isinstance(slot, dict):
            continue
        end = _dt(slot.get("valid_to"))
        if end is None or end > tomorrow_start:
            continue
        if candidate is None or candidate_end is None or end > candidate_end:
            candidate = slot
            candidate_end = end
    if candidate is None:
        return None, None

    soc = _number(candidate.get("flow_estimated_soc_percent"))
    if soc is None:
        soc = _number(candidate.get("ending_soc_percent"))
    return soc, str(candidate.get("label") or candidate.get("local_from") or "")


def reconcile_tomorrow_soc_continuity(
    state: dict[str, Any],
    *,
    config: SimulationConfig,
) -> int:
    """Carry final Today SOC through Tomorrow's already-authoritative slot flows."""
    slots = [
        item
        for item in state.get("tomorrow_slots", []) or []
        if isinstance(item, dict)
    ]
    anchor_soc, anchor_label = _today_midnight_soc(state)
    capacity = max(float(config.battery_capacity_kwh), 0.0)
    discharge_efficiency = max(float(config.discharge_efficiency), 0.01)
    if not slots or anchor_soc is None or capacity <= _EPSILON:
        state["tomorrow_soc_continuity"] = {
            "active": False,
            "reason": "missing Today boundary SOC, Tomorrow slots, or battery capacity",
            "hardware_writes": "blocked",
        }
        return 0

    ordered = sorted(
        slots,
        key=lambda item: _dt(item.get("valid_from"))
        or _dt(item.get("valid_to"))
        or _dt("1970-01-01T00:00:00+00:00"),
    )
    first_before = _number(ordered[0].get("flow_estimated_soc_percent"))
    if first_before is None:
        first_before = _number(ordered[0].get("ending_soc_percent"))

    battery_kwh = capacity * min(max(anchor_soc, 0.0), 100.0) / 100.0
    corrected = 0
    for slot in ordered:
        grid_to_battery = _non_negative(
            slot.get("grid_to_battery_kwh"),
            slot.get("flow_grid_to_battery_kwh"),
        )
        solar_to_battery = _non_negative(
            slot.get("solar_to_battery_kwh"),
            slot.get("flow_solar_to_battery_kwh"),
        )
        battery_to_home = _non_negative(
            slot.get("battery_to_home_kwh"),
            slot.get("flow_battery_to_home_kwh"),
        )
        battery_export = _non_negative(
            slot.get("battery_export_kwh"),
            slot.get("flow_battery_export_kwh"),
        )

        # grid_to_battery / solar_to_battery are already stored battery energy
        # in the canonical slot contract. Home/export are AC delivered energy.
        battery_kwh += grid_to_battery + solar_to_battery
        battery_kwh -= (battery_to_home + battery_export) / discharge_efficiency
        battery_kwh = min(max(battery_kwh, 0.0), capacity)
        soc = 100.0 * battery_kwh / capacity

        slot["ending_soc_percent"] = round(soc, 3)
        flow = build_slot_flow(
            grid_import_kwh=_number(slot.get("grid_import_kwh")),
            solar_generation_kwh=_number(slot.get("solar_generation_kwh")),
            solar_to_home_kwh=_number(slot.get("solar_to_home_kwh")),
            solar_to_battery_kwh=solar_to_battery,
            solar_export_kwh=_number(slot.get("solar_export_kwh")),
            grid_to_battery_kwh=grid_to_battery,
            battery_to_home_kwh=battery_to_home,
            battery_export_kwh=battery_export,
            estimated_soc_percent=soc,
            basis=str(slot.get("flow_basis") or "KEMS forecast replay"),
            scope=str(slot.get("flow_scope") or "full slot"),
        )
        slot.update(flow)
        slot["flow_soc_midnight_continuity_applied"] = True
        slot["flow_soc_midnight_anchor_percent"] = round(anchor_soc, 3)
        slot["flow_soc_hardware_writes"] = "blocked"
        corrected += 1

    first_after = _number(ordered[0].get("flow_estimated_soc_percent"))
    state["tomorrow_soc_continuity"] = {
        "active": True,
        "anchor_source": "final displayed Today SOC at Tomorrow boundary",
        "anchor_label": anchor_label,
        "anchor_soc_percent": round(anchor_soc, 3),
        "first_tomorrow_soc_before_percent": (
            round(first_before, 3) if first_before is not None else None
        ),
        "first_tomorrow_soc_after_percent": (
            round(first_after, 3) if first_after is not None else None
        ),
        "pre_fix_boundary_jump_percent": (
            round(first_before - anchor_soc, 3) if first_before is not None else None
        ),
        "rows_reconciled": corrected,
        "battery_charge_source": (
            "canonical stored grid/solar-to-battery energy; never inferred from SOC"
        ),
        "reporting_only": True,
        "hardware_writes": "blocked",
    }
    return corrected


def build_midnight_plan_continuity_manager(base_class: type) -> type:
    """Return the final reporting owner for continuous Today/Tomorrow SOC."""

    class MidnightPlanContinuityAgileSmartExportManager(base_class):
        async def async_update(self, **kwargs):
            state = await super().async_update(**kwargs)
            config = kwargs.get("config")
            if isinstance(state, dict) and isinstance(config, SimulationConfig):
                reconcile_tomorrow_soc_continuity(state, config=config)
                self._state = state
            return self.state

    MidnightPlanContinuityAgileSmartExportManager.__name__ = (
        "MidnightPlanContinuityAgileSmartExportManager"
    )
    return MidnightPlanContinuityAgileSmartExportManager
