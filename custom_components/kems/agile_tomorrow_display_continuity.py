"""Final Today-to-Tomorrow SOC continuity for customer-facing Agile plans.

The canonical Agile optimiser deliberately has several independent replay and
settlement owners.  After the final Today display SOC has been rebased against
settled/current evidence, Tomorrow must not keep an older independently seeded
SOC path.  This reporting-only owner carries the exact final Today boundary SOC
into Tomorrow and replays Tomorrow's already-planned battery energy deltas from
that boundary.

It also rebuilds each corrected Tomorrow flow row from the authoritative slot
energy fields.  This prevents a slot with real grid-to-battery energy from being
presented as battery IDLE.

No optimiser allocation, dispatch target, ControlState, tariff decision or
hardware-write permission is changed here.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .kems_core import SimulationConfig
from .kems_core.slot_flow import build_slot_flow

_EPSILON = 1e-6


def _number(value: Any) -> float | None:
    """Return one finite float, or None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dt(value: Any) -> datetime | None:
    """Return one aware datetime, or None."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _component(
    slot: dict[str, Any],
    primary: str,
    flow_fallback: str,
) -> float | None:
    """Return a non-negative presentation component when available."""
    value = _number(slot.get(primary))
    if value is None:
        value = _number(slot.get(flow_fallback))
    return max(value, 0.0) if value is not None else None


def _required_battery_component(
    slot: dict[str, Any],
    primary: str,
) -> float | None:
    """Return one authoritative battery component without zero-coercion fallback."""
    value = _number(slot.get(primary))
    return max(value, 0.0) if value is not None else None


def _reconcile_tomorrow_display_continuity(
    state: dict[str, Any],
    *,
    config: SimulationConfig,
) -> int:
    """Carry final Today display SOC into Tomorrow and rebuild flow presentation."""
    today = [item for item in state.get("today_slots", []) if isinstance(item, dict)]
    tomorrow = [
        item for item in state.get("tomorrow_slots", []) if isinstance(item, dict)
    ]
    diagnostic: dict[str, Any] = {
        "active": False,
        "status": "unavailable",
        "corrected_rows": 0,
        "reporting_only": True,
        "hardware_writes": "blocked",
    }
    state["tomorrow_display_continuity"] = diagnostic
    if not today or not tomorrow:
        diagnostic["reason"] = "Today or Tomorrow slot feed is unavailable"
        return 0

    parsed_tomorrow = [(_dt(item.get("valid_from")), item) for item in tomorrow]
    if any(start is None for start, _item in parsed_tomorrow):
        diagnostic["reason"] = "Tomorrow slot boundary timestamp is unavailable"
        return 0
    ordered_tomorrow = [
        item
        for _start, item in sorted(
            parsed_tomorrow,
            key=lambda pair: pair[0],
        )
    ]
    first_start = _dt(ordered_tomorrow[0].get("valid_from"))
    if first_start is None:
        diagnostic["reason"] = "Tomorrow first-slot boundary timestamp is unavailable"
        return 0

    boundary_candidates = [
        item for item in today if _dt(item.get("valid_to")) == first_start
    ]
    if not boundary_candidates:
        diagnostic["reason"] = "No exact Today slot ends at Tomorrow's first boundary"
        return 0
    boundary = sorted(
        boundary_candidates,
        key=lambda item: _dt(item.get("valid_from")) or first_start,
    )[-1]

    handoff_soc = _number(boundary.get("flow_estimated_soc_percent"))
    handoff_source = "flow_estimated_soc_percent"
    if handoff_soc is None:
        handoff_soc = _number(boundary.get("ending_soc_percent"))
        handoff_source = "ending_soc_percent"
    if handoff_soc is None:
        diagnostic["reason"] = "Final Today boundary SOC is unavailable"
        return 0

    capacity = _number(getattr(config, "battery_capacity_kwh", None))
    discharge_efficiency = _number(getattr(config, "discharge_efficiency", None))
    if (
        capacity is None
        or capacity <= _EPSILON
        or discharge_efficiency is None
        or discharge_efficiency <= _EPSILON
    ):
        diagnostic["reason"] = "Battery capacity/discharge efficiency is invalid"
        return 0
    discharge_efficiency = min(discharge_efficiency, 1.0)

    battery_kwh = capacity * min(max(handoff_soc, 0.0), 100.0) / 100.0
    corrected = 0
    first_pre_rebase = _number(ordered_tomorrow[0].get("flow_estimated_soc_percent"))
    stopped_reason: str | None = None

    for slot in ordered_tomorrow:
        grid_charge = _required_battery_component(
            slot,
            "grid_to_battery_kwh",
        )
        solar_charge = _required_battery_component(
            slot,
            "solar_to_battery_kwh",
        )
        battery_home = _required_battery_component(
            slot,
            "battery_to_home_kwh",
        )
        battery_export = _required_battery_component(
            slot,
            "battery_export_kwh",
        )
        if None in (grid_charge, solar_charge, battery_home, battery_export):
            slot_label = slot.get("label") or slot.get("valid_from")
            stopped_reason = f"battery energy components unavailable at {slot_label}"
            break

        pre_flow_soc = _number(slot.get("flow_estimated_soc_percent"))
        pre_ending_soc = _number(slot.get("ending_soc_percent"))
        battery_kwh += grid_charge + solar_charge
        battery_kwh -= (battery_home + battery_export) / discharge_efficiency
        battery_kwh = min(max(battery_kwh, 0.0), capacity)
        rebased_soc = 100.0 * battery_kwh / capacity

        flow = build_slot_flow(
            grid_import_kwh=_component(
                slot,
                "grid_import_kwh",
                "flow_grid_import_kwh",
            ),
            solar_generation_kwh=_component(
                slot,
                "solar_generation_kwh",
                "flow_solar_kwh",
            ),
            solar_to_home_kwh=_component(
                slot,
                "solar_to_home_kwh",
                "flow_solar_to_home_kwh",
            ),
            solar_to_battery_kwh=solar_charge,
            solar_export_kwh=_component(
                slot,
                "solar_export_kwh",
                "flow_solar_export_kwh",
            ),
            grid_to_battery_kwh=grid_charge,
            battery_to_home_kwh=battery_home,
            battery_export_kwh=battery_export,
            estimated_soc_percent=rebased_soc,
            basis="KEMS forecast replay + continuous Today midnight SOC",
            scope=str(slot.get("flow_scope") or "full slot"),
        )
        slot.update(flow)
        slot["pre_midnight_handoff_flow_soc_percent"] = pre_flow_soc
        slot["pre_midnight_handoff_ending_soc_percent"] = pre_ending_soc
        slot["ending_soc_percent"] = round(rebased_soc, 3)
        slot["flow_soc_midnight_rebased"] = True
        slot["flow_soc_hardware_writes"] = "blocked"
        corrected += 1

    diagnostic.update(
        {
            "active": corrected > 0,
            "status": "rebased" if corrected > 0 else "unavailable",
            "boundary_time": first_start.isoformat(),
            "handoff_soc_percent": round(handoff_soc, 3),
            "handoff_source": handoff_source,
            "first_pre_rebase_soc_percent": (
                round(first_pre_rebase, 3) if first_pre_rebase is not None else None
            ),
            "first_rebased_soc_percent": (
                _number(ordered_tomorrow[0].get("flow_estimated_soc_percent"))
                if corrected > 0
                else None
            ),
            "corrected_rows": corrected,
            "stopped_reason": stopped_reason,
            "policy": (
                "Tomorrow inherits the final displayed Today SOC and advances only "
                "through Tomorrow's already-planned battery energy"
            ),
        }
    )
    return corrected


def build_tomorrow_display_continuity_manager(base_class: type) -> type:
    """Return the final reporting owner around the current Agile runtime."""

    class TomorrowDisplayContinuityAgileSmartExportManager(base_class):
        def __init__(self, hass: Any, entry_id: str, history_days: int) -> None:
            super().__init__(hass, entry_id, history_days)
            self._kems_tomorrow_display_config: SimulationConfig | None = None

        async def async_update(self, **kwargs: Any) -> dict[str, Any]:
            config = kwargs.get("config")
            if isinstance(config, SimulationConfig):
                self._kems_tomorrow_display_config = config
            state = await super().async_update(**kwargs)
            active_config = self._kems_tomorrow_display_config
            if active_config is not None:
                _reconcile_tomorrow_display_continuity(
                    state,
                    config=active_config,
                )
                self._state = state
            return self.state

        def reconcile_current_day_settlements(self, **kwargs: Any) -> dict[str, Any]:
            state = super().reconcile_current_day_settlements(**kwargs)
            active_config = self._kems_tomorrow_display_config
            if active_config is not None:
                _reconcile_tomorrow_display_continuity(
                    state,
                    config=active_config,
                )
                self._state = state
            return self.state

    TomorrowDisplayContinuityAgileSmartExportManager.__name__ = (
        "TomorrowDisplayContinuityAgileSmartExportManager"
    )
    return TomorrowDisplayContinuityAgileSmartExportManager