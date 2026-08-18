"""Rolling receding-horizon replanning for Agile Smart Export.

Every normal KEMS coordinator scan re-evaluates the remaining export plan from
current simulated battery energy and the still-unspent Agile slots. Native KEMS
history remains persisted at its normal five-minute cadence; a transient live
snapshot is overlaid in memory so the optimiser can react without inflating
storage.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from . import history as history_module
from .agile_deadline_dispatch import _effective_deadline_kw, _target_percent
from .kems_core import SimulationConfig
from .tariff import TariffSettings

SAFETY_HEADROOM_MINUTES = 30
PRESSURE_THRESHOLD = 0.75
_EPSILON = 1e-6

_ORIGINAL_THRESHOLD = agile._threshold
_ORIGINAL_RUNTIME_UPDATE = runtime.EfficientAgileSmartExportManager.async_update
_ORIGINAL_RUNTIME_PUBLISH = runtime.EfficientAgileSmartExportManager._publish
_ORIGINAL_HISTORY_RECORDS = history_module.HistoryRecorder.records.fget
_ORIGINAL_HISTORY_RECORD = history_module.HistoryRecorder.async_record


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _datetime(value: Any) -> datetime | None:
    """Parse one ISO timestamp as UTC."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value)).astimezone(UTC)
    except ValueError:
        return None


def _current_agile_soc(state: dict[str, Any]) -> float | None:
    """Return the latest simulated SOC from today's Agile replay."""
    periods = state.get("periods")
    if not isinstance(periods, dict):
        return None
    today = periods.get("today")
    if not isinstance(today, dict):
        return None
    strategy = today.get("agile_smart_export")
    if not isinstance(strategy, dict):
        return None
    return _number(strategy.get("ending_soc_percent"))


def _rolling_threshold(
    rates: list[agile.AgileRate],
    start: datetime,
    end: datetime,
    energy: float,
    max_kw: float,
) -> float | None:
    """Keep best-slot ranking but widen it when deadline capacity gets tight."""
    if energy <= 0 or max_kw <= 0:
        return None
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    values = sorted(
        [
            item.value_inc_vat
            for item in rates
            if start_utc <= item.valid_from < end_utc and item.value_inc_vat > 0
        ],
        reverse=True,
    )
    if not values:
        return None

    slot_capacity = max(max_kw * 0.5, 0.001)
    needed = max(1, math.ceil(energy / slot_capacity))
    total_capacity = slot_capacity * len(values)
    utilisation = energy / total_capacity if total_capacity > _EPSILON else 1.0

    # When more than 75% of the remaining positive-price capacity is required,
    # include one additional slot. This preserves price optimisation while no
    # longer riding the absolute mathematical deadline edge.
    if utilisation >= PRESSURE_THRESHOLD and needed < len(values):
        needed += 1
    return values[min(needed, len(values)) - 1]


def _history_records_with_live(self) -> list[Any]:
    """Expose the newest transient snapshot without persisting it every scan."""
    assert _ORIGINAL_HISTORY_RECORDS is not None
    records = list(_ORIGINAL_HISTORY_RECORDS(self))
    live = getattr(self, "_kems_live_snapshot", None)
    if live is not None and (not records or live.timestamp > records[-1].timestamp):
        records.append(live)
    return records


async def _history_record_with_live(self, snapshot) -> bool:
    """Remember every scan for analysis while retaining normal persistence."""
    self._kems_live_snapshot = snapshot
    return await _ORIGINAL_HISTORY_RECORD(self, snapshot)


def _predicted_house_until_deadline(self) -> float:
    """Return protected AC house demand until cheap power starts."""
    value = _number(getattr(self, "_rolling_predicted_house_kwh", None))
    if value is not None:
        return max(value, 0.0)
    records = getattr(self, "_panel_today_records", [])
    if records:
        fallback = _number(records[-1].forecast_expected_house_remaining_today_kwh)
        if fallback is not None:
            return max(fallback, 0.0)
    return 0.0


def _current_house_headroom_kw(self, config: SimulationConfig) -> float:
    """Estimate battery power already needed by the house in the active slot."""
    records = getattr(self, "_panel_today_records", [])
    if not records:
        return 0.0
    current = records[-1]
    house = _number(current.house_load_kw) or 0.0
    solar = _number(current.solar_power_kw) or 0.0
    return min(max(house - solar, 0.0), max(config.max_discharge_kw, 0.0))


def _rolling_plan(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Allocate currently exportable battery energy across remaining Agile slots."""
    soc = _current_agile_soc(state)
    effective_kw = _effective_deadline_kw(config)
    capacity = max(config.battery_capacity_kwh, 0.1)
    efficiency = max(config.discharge_efficiency, 0.01)
    target_soc = _target_percent(config)
    deadline = agile._next_cheap(now, tariff).astimezone(UTC)
    now_utc = now.astimezone(UTC)
    protected_house_ac = _predicted_house_until_deadline(self)

    if soc is None or effective_kw <= _EPSILON or deadline <= now_utc:
        return {
            "available": False,
            "generated_at": now.isoformat(),
            "reason": "waiting for current simulated SOC or remaining discharge path",
            "target_soc_percent": target_soc,
        }

    battery_kwh = capacity * min(max(soc, 0.0), 100.0) / 100.0
    target_kwh = capacity * target_soc / 100.0
    protected_stored_kwh = min(
        target_kwh + protected_house_ac / efficiency,
        capacity,
    )
    exportable_ac = max(battery_kwh - protected_stored_kwh, 0.0) * efficiency

    slots = state.get("today_slots")
    if not isinstance(slots, list):
        slots = []
    candidates: list[dict[str, Any]] = []
    current_house_kw = _current_house_headroom_kw(self, config)
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        start = _datetime(slot.get("valid_from"))
        end = _datetime(slot.get("valid_to"))
        if start is None or end is None:
            continue
        overlap_start = max(start, now_utc)
        overlap_end = min(end, deadline)
        if overlap_end <= overlap_start:
            continue
        hours = (overlap_end - overlap_start).total_seconds() / 3600.0
        available_kw = effective_kw
        is_current = start <= now_utc < end
        if is_current:
            available_kw = max(available_kw - current_house_kw, 0.0)
        candidates.append(
            {
                "slot": slot,
                "start": start,
                "end": end,
                "rate": _number(slot.get("rate_pence")) or 0.0,
                "capacity_kwh": max(available_kw * hours, 0.0),
                "is_current": is_current,
                "allocation_kwh": 0.0,
            }
        )

    total_capacity = sum(item["capacity_kwh"] for item in candidates)
    desired = min(exportable_ac, total_capacity)
    current = next((item for item in candidates if item["is_current"]), None)
    current_capacity = current["capacity_kwh"] if current is not None else 0.0
    safety_headroom = min(
        effective_kw * SAFETY_HEADROOM_MINUTES / 60.0,
        total_capacity,
    )

    # If skipping the current slot would leave less than one half-hour of spare
    # discharge capacity, activate enough of this slot to restore that margin.
    required_now = max(
        desired + safety_headroom - max(total_capacity - current_capacity, 0.0),
        0.0,
    )
    if current is not None and desired > _EPSILON:
        forced = min(required_now, current_capacity, desired)
        current["allocation_kwh"] = forced

    remaining = max(
        desired - sum(item["allocation_kwh"] for item in candidates),
        0.0,
    )
    for item in sorted(candidates, key=lambda value: value["rate"], reverse=True):
        if remaining <= _EPSILON:
            break
        spare = max(item["capacity_kwh"] - item["allocation_kwh"], 0.0)
        allocated = min(remaining, spare)
        item["allocation_kwh"] += allocated
        remaining -= allocated

    selected: list[dict[str, Any]] = []
    for item in sorted(candidates, key=lambda value: value["start"]):
        slot = item["slot"]
        allocation = round(float(item["allocation_kwh"]), 3)
        slot["rolling_planned_battery_export_kwh"] = allocation
        slot["rolling_replan_generated_at"] = now.isoformat()
        if item["end"] > now_utc:
            if allocation > 0:
                slot["rolling_action"] = "planned battery export — rolling replan"
                if not item["is_current"]:
                    slot["battery_export_kwh"] = allocation
                    slot["actions"] = ["planned battery export — rolling replan"]
            else:
                slot["rolling_action"] = "hold — re-evaluate next KEMS scan"
                if not item["is_current"]:
                    slot["actions"] = ["hold — rolling replan"]
        if allocation > 0:
            selected.append(
                {
                    "valid_from": slot.get("valid_from"),
                    "label": slot.get("label"),
                    "rate_pence": round(float(item["rate"]), 5),
                    "planned_battery_export_kwh": allocation,
                    "deadline_forced": bool(
                        item["is_current"] and required_now > _EPSILON
                    ),
                }
            )

    next_slot = next(
        (
            item
            for item in selected
            if (_datetime(item.get("valid_from")) or now_utc) >= now_utc
        ),
        selected[0] if selected else None,
    )
    planned = sum(item["planned_battery_export_kwh"] for item in selected)
    return {
        "available": True,
        "generated_at": now.isoformat(),
        "replan_policy": "every KEMS coordinator scan",
        "target_soc_percent": round(target_soc, 1),
        "simulated_soc_percent": round(soc, 1),
        "protected_house_energy_kwh": round(protected_house_ac, 3),
        "exportable_battery_energy_kwh": round(exportable_ac, 3),
        "planned_battery_export_kwh": round(planned, 3),
        "effective_discharge_kw": round(effective_kw, 3),
        "remaining_slot_capacity_kwh": round(total_capacity, 3),
        "safety_headroom_kwh": round(safety_headroom, 3),
        "deadline_capacity_margin_kwh": round(total_capacity - desired, 3),
        "required_in_current_slot_kwh": round(
            min(required_now, current_capacity, desired), 3
        ),
        "selected_slots": selected,
        "next_export_slot": next_slot,
        "unallocated_exportable_kwh": round(max(exportable_ac - planned, 0.0), 3),
    }


async def _async_update_with_rolling(
    self,
    *,
    records,
    now,
    config,
    learned,
    forecast,
    forecast_plan,
    tariff,
):
    """Capture live planning context and re-run analysis every coordinator scan."""
    self._rolling_now = now
    self._rolling_config = config
    self._rolling_tariff = tariff
    self._rolling_predicted_house_kwh = getattr(
        learned,
        "predicted_energy_until_offpeak_kwh",
        None,
    )
    return await _ORIGINAL_RUNTIME_UPDATE(
        self,
        records=records,
        now=now,
        config=config,
        learned=learned,
        forecast=forecast,
        forecast_plan=forecast_plan,
        tariff=tariff,
    )


def _publish_with_rolling(self, state: dict[str, Any]) -> None:
    """Attach the current rolling allocation before normal dashboard publishing."""
    now = getattr(self, "_rolling_now", None)
    config = getattr(self, "_rolling_config", None)
    tariff = getattr(self, "_rolling_tariff", None)
    if (
        isinstance(now, datetime)
        and isinstance(config, SimulationConfig)
        and isinstance(tariff, TariffSettings)
    ):
        state["rolling_export_plan"] = _rolling_plan(
            self,
            state,
            now=now,
            config=config,
            tariff=tariff,
        )

    _ORIGINAL_RUNTIME_PUBLISH(self, state)
    plan = state.get("rolling_export_plan", {})
    plan = plan if isinstance(plan, dict) else {}
    selected = plan.get("selected_slots", [])
    selected = selected if isinstance(selected, list) else []
    next_slot = plan.get("next_export_slot")
    next_label = (
        str(next_slot.get("label") or "Unavailable")
        if isinstance(next_slot, dict)
        else "Unavailable"
    )
    self._set(
        "sensor.kems_agile_rolling_export_plan",
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
    for entity_id, value, name, unit in (
        (
            "sensor.kems_agile_rolling_exportable_energy",
            plan.get("exportable_battery_energy_kwh"),
            "Agile rolling exportable battery energy",
            "kWh",
        ),
        (
            "sensor.kems_agile_rolling_protected_house_energy",
            plan.get("protected_house_energy_kwh"),
            "Agile rolling protected house energy",
            "kWh",
        ),
        (
            "sensor.kems_agile_rolling_capacity_margin",
            plan.get("deadline_capacity_margin_kwh"),
            "Agile rolling deadline capacity margin",
            "kWh",
        ),
    ):
        self._set(
            entity_id,
            agile._state(value),
            {
                "friendly_name": name,
                "unit_of_measurement": unit,
                "generated_at": plan.get("generated_at"),
            },
        )
    self._set(
        "sensor.kems_agile_rolling_next_export_slot",
        next_label,
        {
            "friendly_name": "Agile rolling next battery export slot",
            "slot": next_slot,
            "generated_at": plan.get("generated_at"),
        },
    )


def install_rolling_replan_patch() -> None:
    """Install rolling analysis, live-snapshot overlay, and slot allocation once."""
    runtime.ANALYSIS_REFRESH = timedelta(0)

    threshold = agile._threshold
    if not getattr(threshold, "_kems_rolling_replan", False):
        _rolling_threshold._kems_rolling_replan = True
        agile._threshold = _rolling_threshold

    records_property = history_module.HistoryRecorder.records
    if not getattr(records_property.fget, "_kems_live_overlay", False):
        _history_records_with_live._kems_live_overlay = True
        history_module.HistoryRecorder.records = property(_history_records_with_live)

    record = history_module.HistoryRecorder.async_record
    if not getattr(record, "_kems_live_overlay", False):
        _history_record_with_live._kems_live_overlay = True
        history_module.HistoryRecorder.async_record = _history_record_with_live

    update = runtime.EfficientAgileSmartExportManager.async_update
    if not getattr(update, "_kems_rolling_replan", False):
        _async_update_with_rolling._kems_rolling_replan = True
        runtime.EfficientAgileSmartExportManager.async_update = (
            _async_update_with_rolling
        )

    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_rolling_replan", False):
        _publish_with_rolling._kems_rolling_replan = True
        runtime.EfficientAgileSmartExportManager._publish = _publish_with_rolling
