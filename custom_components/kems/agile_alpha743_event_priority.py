"""Alpha7.43 Power Down priority and manual Weekend Happy Hour planning.

Power Down is an absolute event priority.  Agile price ranking is never allowed
to spend the battery energy needed to run the house and maximise safe export in
a joined Power Down session.  During the session the current Agile price is
ignored: solar/battery serve the house and every remaining safe watt is offered
to grid export within the configured inverter, battery and export limits.

Weekend Happy Hours are currently chosen by the customer in Octopus' own UI and
are not exposed by the Home Assistant Octopus integration.  Alpha7.43 therefore
adds a small manual event input.  Before the free hour KEMS creates only the
additional battery headroom needed to charge at the highest safe rate, choosing
the best *known* Agile price slots before the event.  During the Happy Hour it
holds deliberate discharge/export at zero and exposes a maximum safe charge
target.  After the event the rolling planner sees a corrected digital-twin SOC
and can sell the replenished energy into later Agile slots.

This remains simulation/shadow only.  No FoxESS write path is introduced.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from . import agile_alpha717_dispatch as alpha717
from . import agile_alpha731_solar_headroom as alpha731
from . import agile_rolling_replan as rolling
from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from .happy_hour import manual_happy_hour_event
from .kems_core import SimulationConfig
from .tariff import TariffSettings

_EPSILON = 1e-6
_POWER_DOWN_SENSOR = "sensor.kems_agile_power_down_priority"
_HAPPY_HOUR_SENSOR = "sensor.kems_agile_happy_hour_plan"
_EVENT_PRIORITY_SENSOR = "sensor.kems_agile_event_priority"
_ALPHA743_SENSOR_IDS = (
    _POWER_DOWN_SENSOR,
    _HAPPY_HOUR_SENSOR,
    _EVENT_PRIORITY_SENSOR,
)

_DASHBOARD_MARKER = """          This page keeps the operating view deliberately simple. Detailed price-slot, validation and shadow evidence remains available in KEMS diagnostics.

      - type: grid
        columns: 4
"""
_DASHBOARD_INSERT = """          This page keeps the operating view deliberately simple. Detailed price-slot, validation and shadow evidence remains available in KEMS diagnostics.

      - type: entities
        title: Octopus event planning
        show_header_toggle: false
        entities:
          - switch.kems_weekend_happy_hour_planning
          - datetime.kems_weekend_happy_hour_start
          - select.kems_weekend_happy_hour_duration
          - sensor.kems_agile_happy_hour_plan
          - sensor.kems_agile_power_down_priority

      - type: grid
        columns: 4
"""


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dt(value: Any) -> datetime | None:
    """Parse one aware timestamp and normalise it to UTC."""
    if value is None:
        return None
    try:
        parsed = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _entry_options(self) -> dict[str, Any]:
    """Return this Agile manager's config-entry options."""
    entry_id = getattr(self, "_kems_alpha743_entry_id", None)
    if not entry_id:
        return {}
    entry = self._hass.config_entries.async_get_entry(str(entry_id))
    return dict(entry.options) if entry is not None else {}


def _latest_snapshot(self):
    records = list(getattr(self, "_panel_today_records", []) or [])
    return records[-1] if records else None


def _base_soc(state: dict[str, Any]) -> float | None:
    """Read today's unadjusted Agile replay SOC without calling patched helpers."""
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


def _recent_house_load_kw(self) -> float:
    """Return a short recent average house load for event sizing."""
    records = list(getattr(self, "_panel_today_records", []) or [])
    if not records:
        return 0.0
    latest = records[-1].timestamp.astimezone(UTC)
    cutoff = latest - timedelta(hours=1)
    values: list[float] = []
    for item in records:
        if item.timestamp.astimezone(UTC) < cutoff:
            continue
        value = _number(getattr(item, "house_load_kw", None))
        if value is None:
            value = _number(getattr(item, "grid_import_kw", None))
        if value is not None:
            values.append(max(value, 0.0))
    if values:
        return sum(values) / len(values)
    value = _number(getattr(records[-1], "house_load_kw", None))
    if value is None:
        value = _number(getattr(records[-1], "grid_import_kw", None))
    return max(value or 0.0, 0.0)


def _current_solar_kw(self, config: SimulationConfig) -> float:
    """Use the same routed solar basis as the existing shared-inverter guard."""
    try:
        evidence = alpha731._proposal_solar_evidence(self, config)
    except (AttributeError, TypeError, ValueError):
        evidence = None
    if isinstance(evidence, dict) and evidence.get("available"):
        value = _number(evidence.get("routed_solar_ac_kw"))
        if value is not None:
            return min(max(value, 0.0), max(config.inverter_limit_kw, 0.0))
    snapshot = _latest_snapshot(self)
    value = _number(getattr(snapshot, "solar_power_kw", None)) if snapshot else None
    return min(max(value or 0.0, 0.0), max(config.inverter_limit_kw, 0.0))


def _power_down_context(
    self,
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Describe the active/next joined Power Down and its protected export reserve."""
    snapshot = _latest_snapshot(self)
    if snapshot is None or not config.saving_session_enabled:
        return {"available": False, "status": "No joined Power Down"}
    if not bool(getattr(snapshot, "saving_session_joined", False)):
        return {"available": False, "status": "No joined Power Down"}

    start = _dt(getattr(snapshot, "saving_session_start", None))
    end = _dt(getattr(snapshot, "saving_session_end", None))
    now_utc = now.astimezone(UTC)
    if start is None or end is None or end <= start or end <= now_utc:
        return {"available": False, "status": "No upcoming joined Power Down"}

    active = start <= now_utc < end
    duration = (end - start).total_seconds() / 3600.0
    house_kw = _recent_house_load_kw(self)
    battery_total_kw = min(
        max(config.max_discharge_kw, 0.0),
        max(config.inverter_limit_kw, 0.0),
    )
    export_target_kw = min(
        max(config.export_limit_kw, 0.0),
        max(battery_total_kw - house_kw, 0.0),
    )
    reserve_export_ac = export_target_kw * duration
    reserve_export_stored = reserve_export_ac / max(config.discharge_efficiency, 0.01)
    next_cheap = agile._next_cheap(now, tariff).astimezone(UTC)
    reserve_required_now = bool(not active and start < next_cheap)

    return {
        "available": True,
        "joined": True,
        "active": active,
        "status": (
            "Active — absolute priority" if active else "Reserved — absolute priority"
        ),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_hours": round(duration, 3),
        "expected_house_load_kw": round(house_kw, 3),
        "maximum_battery_output_kw": round(battery_total_kw, 3),
        "reserved_export_target_kw": round(export_target_kw, 3),
        "reserved_export_energy_kwh": round(reserve_export_ac, 3),
        "reserved_stored_energy_kwh": round(reserve_export_stored, 3),
        "reserve_required_before_next_cheap": reserve_required_now,
        "priority": "absolute_over_agile_price",
        "agile_price_can_override": False,
        "solar_forecast_required_for_reserve": False,
        "house_first": True,
        "maximise_safe_export": True,
        "ev_charging_allowed_during_event": False,
        "hardware_writes": "blocked",
    }


def _active_power_down_targets(
    self,
    state: dict[str, Any],
    context: dict[str, Any],
    config: SimulationConfig,
) -> dict[str, Any]:
    """Return the maximum safe active-session battery/solar routing target."""
    house = _recent_house_load_kw(self)
    solar = _current_solar_kw(self, config)
    solar_to_home = min(house, solar)
    solar_export = min(
        max(solar - solar_to_home, 0.0),
        max(config.export_limit_kw, 0.0),
    )
    battery_inverter_headroom = min(
        max(config.max_discharge_kw, 0.0),
        max(config.inverter_limit_kw - solar, 0.0),
    )
    soc = rolling._current_agile_soc(state)
    reserve = max(config.battery_reserve_percent, 0.0)
    battery_allowed = soc is None or soc > reserve + 0.05
    house_battery = (
        min(max(house - solar_to_home, 0.0), battery_inverter_headroom)
        if battery_allowed
        else 0.0
    )
    battery_export = (
        min(
            max(config.export_limit_kw - solar_export, 0.0),
            max(battery_inverter_headroom - house_battery, 0.0),
        )
        if battery_allowed
        else 0.0
    )
    grid_export = min(solar_export + battery_export, max(config.export_limit_kw, 0.0))
    grid_import = max(house - solar_to_home - house_battery, 0.0)
    total_battery = house_battery + battery_export
    total_inverter = solar + total_battery
    return {
        "mode": "power_down_session",
        "action": "Power Down priority — house first, then maximum safe export",
        "house_battery_kw": round(house_battery, 3),
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
    }


def _slot_bounds(slot: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    return _dt(slot.get("valid_from")), _dt(slot.get("valid_to"))


def _overlap_hours(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> float:
    start = max(first_start, second_start)
    end = min(first_end, second_end)
    return max((end - start).total_seconds() / 3600.0, 0.0)


def _selected_current_export_kw(
    selected: list[dict[str, Any]],
    now: datetime,
) -> float:
    """Convert the selected current-slot allocation to a remaining-slot power."""
    now_utc = now.astimezone(UTC)
    for item in selected:
        start, end = _slot_bounds(item)
        if start is None or end is None or not (start <= now_utc < end):
            continue
        hours = max((end - now_utc).total_seconds() / 3600.0, 0.0)
        energy = max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
        return energy / hours if hours > _EPSILON else 0.0
    return 0.0


def _trim_selected_for_power_down(
    selected_value: Any,
    *,
    allowed_kwh: float,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep only the best-priced ordinary export that remains above event reserve."""
    selected = [dict(item) for item in selected_value or [] if isinstance(item, dict)]
    pd_start = _dt(context.get("start"))
    pd_end = _dt(context.get("end"))
    candidates: list[dict[str, Any]] = []
    for item in selected:
        start, end = _slot_bounds(item)
        if (
            start is not None
            and end is not None
            and pd_start is not None
            and pd_end is not None
            and _overlap_hours(start, end, pd_start, pd_end) > _EPSILON
        ):
            continue
        candidates.append(item)

    remaining = max(allowed_kwh, 0.0)
    output: list[dict[str, Any]] = []
    for item in sorted(
        candidates,
        key=lambda value: _number(value.get("rate_pence")) or 0.0,
        reverse=True,
    ):
        if remaining <= _EPSILON:
            break
        energy = max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
        kept = min(energy, remaining)
        if kept <= _EPSILON:
            continue
        item["planned_battery_export_kwh"] = round(kept, 3)
        item["power_down_priority_limited"] = kept + _EPSILON < energy
        output.append(item)
        remaining -= kept
    output.sort(
        key=lambda value: _dt(value.get("valid_from"))
        or datetime.max.replace(tzinfo=UTC)
    )
    return output


def _apply_power_down_to_plan(
    plan: dict[str, Any],
    context: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Reserve the joined session before any ordinary Agile-price allocation."""
    plan["power_down_priority"] = dict(context)
    if not context.get("available"):
        return plan
    if context.get("active"):
        plan["dispatch_mode"] = "power_down_session"
        plan["dispatch_action"] = "Power Down priority — Agile price ignored"
        return plan
    if not context.get("reserve_required_before_next_cheap"):
        return plan

    exportable = max(_number(plan.get("exportable_battery_energy_kwh")) or 0.0, 0.0)
    reserved = max(_number(context.get("reserved_export_energy_kwh")) or 0.0, 0.0)
    allowed = max(exportable - reserved, 0.0)
    selected = _trim_selected_for_power_down(
        plan.get("selected_slots"),
        allowed_kwh=allowed,
        context=context,
    )
    planned = sum(
        max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
        for item in selected
    )
    current_kw = _selected_current_export_kw(selected, now)
    plan.update(
        {
            "exportable_battery_energy_kwh": round(allowed, 3),
            "power_down_reserved_export_energy_kwh": round(reserved, 3),
            "normal_agile_exportable_after_power_down_kwh": round(allowed, 3),
            "planned_battery_export_kwh": round(planned, 3),
            "selected_slots": selected,
            "next_export_slot": next(
                (
                    item
                    for item in selected
                    if (_dt(item.get("valid_from")) or now.astimezone(UTC))
                    >= now.astimezone(UTC)
                ),
                None,
            ),
            "current_battery_export_target_kw": round(current_kw, 3),
            "power_down_reserve_is_price_independent": True,
        }
    )
    return plan


def _happy_hour_event(self) -> dict[str, Any]:
    return manual_happy_hour_event(_entry_options(self))


def _happy_hour_charge_target(
    self,
    event: dict[str, Any],
    config: SimulationConfig,
) -> dict[str, float]:
    """Return the maximum useful free-grid charge while respecting local limits."""
    duration = max(float(event.get("duration_hours") or 1.0), 0.0)
    house_kw = _recent_house_load_kw(self)
    fair_cap = max(float(event.get("fair_use_cap_kwh") or 0.0), 0.0)
    fair_use_charge_kw = max(fair_cap / max(duration, 0.001) - house_kw, 0.0)
    site_charge_kw = float("inf")
    if config.site_import_limit_kw is not None:
        site_charge_kw = max(float(config.site_import_limit_kw) - house_kw, 0.0)
    charge_kw = min(
        max(config.max_charge_kw, 0.0),
        max(config.inverter_limit_kw, 0.0),
        fair_use_charge_kw,
        site_charge_kw,
    )
    charge_input = charge_kw * duration
    stored = charge_input * max(config.charge_efficiency, 0.01)
    return {
        "expected_house_import_kw": round(house_kw, 3),
        "charge_target_kw": round(charge_kw, 3),
        "charge_input_kwh": round(charge_input, 3),
        "stored_charge_kwh": round(stored, 3),
    }


def _candidate_prep_slots(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    event_start: datetime,
    required_kwh: float,
    safe_available_kwh: float,
    config: SimulationConfig,
    tariff: TariffSettings,
    power_down: dict[str, Any],
) -> tuple[list[dict[str, Any]], float]:
    """Allocate exactly the required headroom into the best known pre-event slots."""
    now_utc = now.astimezone(UTC)
    effective_kw = min(
        max(config.max_discharge_kw, 0.0),
        max(config.inverter_limit_kw, 0.0),
        max(config.export_limit_kw, 0.0),
    )
    current_house_kw = max(rolling._current_house_headroom_kw(self, config), 0.0)
    pd_start = _dt(power_down.get("start")) if power_down.get("available") else None
    pd_end = _dt(power_down.get("end")) if power_down.get("available") else None
    candidates: list[dict[str, Any]] = []
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        start, end = _slot_bounds(slot)
        rate = _number(slot.get("rate_pence"))
        if start is None or end is None or rate is None or rate <= 0:
            continue
        overlap_start = max(start, now_utc)
        overlap_end = min(end, event_start)
        if overlap_end <= overlap_start:
            continue
        local = overlap_start.astimezone(agile.LONDON)
        if agile._in_window(local.time(), tariff.offpeak_start, tariff.offpeak_end):
            continue
        if (
            pd_start is not None
            and pd_end is not None
            and _overlap_hours(overlap_start, overlap_end, pd_start, pd_end) > _EPSILON
        ):
            continue
        hours = (overlap_end - overlap_start).total_seconds() / 3600.0
        slot_kw = effective_kw
        if start <= now_utc < end:
            slot_kw = max(slot_kw - current_house_kw, 0.0)
        candidates.append(
            {
                "valid_from": start.isoformat(),
                "valid_to": end.isoformat(),
                "label": str(
                    slot.get("label")
                    or start.astimezone(agile.LONDON).strftime("%H:%M")
                ),
                "rate_pence": round(rate, 5),
                "capacity_kwh": max(slot_kw * hours, 0.0),
            }
        )

    remaining = min(max(required_kwh, 0.0), max(safe_available_kwh, 0.0))
    selected: list[dict[str, Any]] = []
    for item in sorted(candidates, key=lambda value: value["rate_pence"], reverse=True):
        if remaining <= _EPSILON:
            break
        allocation = min(float(item["capacity_kwh"]), remaining)
        if allocation <= _EPSILON:
            continue
        selected.append(
            {
                "valid_from": item["valid_from"],
                "valid_to": item["valid_to"],
                "label": item["label"],
                "rate_pence": item["rate_pence"],
                "planned_battery_export_kwh": round(allocation, 3),
                "happy_hour_headroom_preparation": True,
            }
        )
        remaining -= allocation
    selected.sort(
        key=lambda value: _dt(value.get("valid_from"))
        or datetime.max.replace(tzinfo=UTC)
    )
    return selected, round(max(remaining, 0.0), 3)


def _best_post_happy_hour_slot(
    state: dict[str, Any],
    *,
    event_end: datetime,
    deadline: datetime,
) -> dict[str, Any] | None:
    """Return the strongest currently published later Agile opportunity."""
    candidates = []
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        start, end = _slot_bounds(slot)
        rate = _number(slot.get("rate_pence"))
        if (
            start is None
            or end is None
            or rate is None
            or rate <= 0
            or start < event_end
            or start >= deadline
        ):
            continue
        candidates.append((rate, start, slot))
    if not candidates:
        return None
    rate, start, slot = max(candidates, key=lambda value: value[0])
    return {
        "valid_from": start.isoformat(),
        "label": str(
            slot.get("label") or start.astimezone(agile.LONDON).strftime("%H:%M")
        ),
        "rate_pence": round(rate, 5),
    }


def _happy_hour_context(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
    power_down: dict[str, Any],
    safe_available_kwh: float | None = None,
) -> dict[str, Any]:
    """Build manual Happy Hour charge/headroom/re-sale evidence."""
    event = _happy_hour_event(self)
    start = _dt(event.get("start"))
    end = _dt(event.get("end"))
    if not event.get("enabled"):
        return {
            "available": False,
            "enabled": False,
            "status": "Disabled",
            "source": "manual",
        }
    if start is None or end is None:
        return {
            "available": False,
            "enabled": True,
            "status": "Set a Weekend Happy Hour start time",
            "source": "manual",
        }

    now_utc = now.astimezone(UTC)
    duration = float(event.get("duration_hours") or 1.0)
    charge = _happy_hour_charge_target(self, event, config)
    capacity = max(config.battery_capacity_kwh, 0.1)
    efficiency = max(config.discharge_efficiency, 0.01)
    reserve_stored = capacity * max(config.battery_reserve_percent, 0.0) / 100.0
    desired_stored_charge = float(charge["stored_charge_kwh"])
    target_entry_stored = max(capacity - desired_stored_charge, reserve_stored)
    target_entry_soc = 100.0 * target_entry_stored / capacity
    soc = _base_soc(state)
    current_stored = (
        capacity * min(max(soc, 0.0), 100.0) / 100.0 if soc is not None else None
    )
    current_headroom = capacity - current_stored if current_stored is not None else 0.0
    next_cheap = agile._next_cheap(now, tariff).astimezone(UTC)

    expected_home_ac = 0.0
    if now_utc < start < next_cheap:
        total_home = max(rolling._predicted_house_until_deadline(self), 0.0)
        total_hours = max((next_cheap - now_utc).total_seconds() / 3600.0, 0.001)
        pre_hours = max((start - now_utc).total_seconds() / 3600.0, 0.0)
        expected_home_ac = total_home * min(pre_hours / total_hours, 1.0)
    expected_home_stored = expected_home_ac / efficiency

    expected_pd_extra_stored = 0.0
    pd_start = _dt(power_down.get("start")) if power_down.get("available") else None
    pd_end = _dt(power_down.get("end")) if power_down.get("available") else None
    if (
        pd_start is not None
        and pd_end is not None
        and now_utc <= pd_start
        and pd_end <= start
    ):
        expected_pd_extra_stored = (
            max(_number(power_down.get("reserved_export_energy_kwh")) or 0.0, 0.0)
            / efficiency
        )

    required_stored_headroom = max(
        desired_stored_charge
        - current_headroom
        - expected_home_stored
        - expected_pd_extra_stored,
        0.0,
    )
    required_export_ac = required_stored_headroom * efficiency
    safe_available = (
        max(float(safe_available_kwh), 0.0)
        if safe_available_kwh is not None
        else float("inf")
    )
    prep_slots: list[dict[str, Any]] = []
    prep_shortfall = 0.0
    preparation_in_current_horizon = bool(now_utc < start < next_cheap)
    if preparation_in_current_horizon and required_export_ac > _EPSILON:
        prep_slots, prep_shortfall = _candidate_prep_slots(
            self,
            state,
            now=now,
            event_start=start,
            required_kwh=required_export_ac,
            safe_available_kwh=safe_available,
            config=config,
            tariff=tariff,
            power_down=power_down,
        )

    pd_overlap = bool(
        pd_start is not None
        and pd_end is not None
        and _overlap_hours(start, end, pd_start, pd_end) > _EPSILON
    )
    if start <= now_utc < end and pd_overlap and power_down.get("active"):
        mode = "power_down_override"
        status = "Power Down active — Happy Hour charge yields to event priority"
    elif start <= now_utc < end:
        mode = "charging"
        status = f"Charging target {float(charge['charge_target_kw']):.2f} kW"
    elif now_utc >= end:
        mode = "complete"
        status = "Complete — Agile re-optimising replenished energy"
    elif start >= next_cheap:
        mode = "scheduled_after_recharge"
        status = "Scheduled — headroom planning starts after the next cheap recharge"
    elif required_export_ac > _EPSILON:
        mode = "preparation"
        status = f"Preparing {required_export_ac:.2f} kWh battery headroom"
    else:
        mode = "ready"
        status = "Scheduled — required charging headroom already forecast"

    prep_energy = sum(
        max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
        for item in prep_slots
    )
    projected_entry_stored = (
        max(
            (current_stored or reserve_stored)
            - expected_home_stored
            - expected_pd_extra_stored
            - prep_energy / efficiency,
            reserve_stored,
        )
        if current_stored is not None
        else None
    )
    projected_post_stored = (
        min(projected_entry_stored + desired_stored_charge, capacity)
        if projected_entry_stored is not None
        else None
    )
    best_post = _best_post_happy_hour_slot(
        state,
        event_end=end,
        deadline=agile._next_cheap(max(now, end), tariff).astimezone(UTC),
    )
    return {
        "available": True,
        "enabled": True,
        "source": "manual",
        "automatic_source_supported": False,
        "status": status,
        "mode": mode,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_hours": duration,
        "fair_use_cap_kwh": float(event.get("fair_use_cap_kwh") or 0.0),
        **charge,
        "current_simulated_soc_percent": soc,
        "current_battery_headroom_kwh": round(current_headroom, 3),
        "target_entry_soc_percent": round(target_entry_soc, 2),
        "desired_stored_charge_kwh": round(desired_stored_charge, 3),
        "expected_house_discharge_before_event_kwh": round(expected_home_ac, 3),
        "expected_power_down_export_before_event_kwh": round(
            expected_pd_extra_stored * efficiency,
            3,
        ),
        "required_headroom_export_kwh": round(required_export_ac, 3),
        "headroom_preparation_slots": prep_slots,
        "headroom_preparation_shortfall_kwh": round(prep_shortfall, 3),
        "preparation_in_current_horizon": preparation_in_current_horizon,
        "projected_entry_soc_percent": (
            round(100.0 * projected_entry_stored / capacity, 2)
            if projected_entry_stored is not None
            else None
        ),
        "projected_post_happy_hour_soc_percent": (
            round(100.0 * projected_post_stored / capacity, 2)
            if projected_post_stored is not None
            else None
        ),
        "best_known_post_happy_hour_export_slot": best_post,
        "power_down_overlap": pd_overlap,
        "priority_order": "safety > Power Down > Happy Hour > Agile price",
        "unknown_price_policy": "never guess a pre/post Happy Hour Agile price",
        "hardware_writes": "blocked",
    }


def _corrected_happy_hour_soc(
    self,
    state: dict[str, Any],
    context: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    power_down: dict[str, Any],
) -> float | None:
    """Correct the rolling SOC for free charging missing from the base replay."""
    base_soc = _base_soc(state)
    start = _dt(context.get("start"))
    end = _dt(context.get("end"))
    if base_soc is None or start is None or end is None or now.astimezone(UTC) < start:
        return None
    if context.get("power_down_overlap") and power_down.get("active"):
        return None

    now_utc = now.astimezone(UTC)
    elapsed_end = min(now_utc, end)
    elapsed_hours = max((elapsed_end - start).total_seconds() / 3600.0, 0.0)
    charge_kw = max(_number(context.get("charge_target_kw")) or 0.0, 0.0)
    free_stored = charge_kw * elapsed_hours * max(config.charge_efficiency, 0.01)

    replay_discharge_ac = 0.0
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        slot_start, slot_end = _slot_bounds(slot)
        if slot_start is None or slot_end is None:
            continue
        if _overlap_hours(slot_start, slot_end, start, elapsed_end) <= _EPSILON:
            continue
        replay_discharge_ac += max(
            _number(slot.get("battery_to_home_kwh")) or 0.0,
            0.0,
        )
        replay_discharge_ac += max(
            _number(slot.get("battery_export_kwh")) or 0.0,
            0.0,
        )

    capacity = max(config.battery_capacity_kwh, 0.1)
    base_stored = capacity * min(max(base_soc, 0.0), 100.0) / 100.0
    corrected = min(
        base_stored
        + replay_discharge_ac / max(config.discharge_efficiency, 0.01)
        + free_stored,
        capacity,
    )
    return round(100.0 * corrected / capacity, 2)


def _apply_happy_hour_to_plan(
    plan: dict[str, Any],
    context: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Make headroom preparation the only deliberate export before the free hour."""
    plan["happy_hour_plan"] = dict(context)
    if not context.get("available"):
        return plan
    mode = str(context.get("mode") or "")
    if mode == "charging":
        plan.update(
            {
                "dispatch_mode": "happy_hour_charge",
                "dispatch_action": "Weekend Happy Hour — maximum safe free-grid charge",
                "selected_slots": [],
                "planned_battery_export_kwh": 0.0,
                "next_export_slot": context.get(
                    "best_known_post_happy_hour_export_slot"
                ),
                "current_battery_export_target_kw": 0.0,
                "current_battery_discharge_target_kw": 0.0,
                "current_battery_charge_target_kw": context.get("charge_target_kw"),
            }
        )
        return plan
    if mode == "power_down_override":
        return plan
    if mode not in {"preparation", "ready"} or not context.get(
        "preparation_in_current_horizon"
    ):
        return plan

    selected = [
        dict(item)
        for item in context.get("headroom_preparation_slots", [])
        if isinstance(item, dict)
    ]
    planned = sum(
        max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
        for item in selected
    )
    current_kw = _selected_current_export_kw(selected, now)
    plan.update(
        {
            "dispatch_mode": (
                "happy_hour_preparation" if planned > _EPSILON else "happy_hour_hold"
            ),
            "dispatch_action": (
                "Create only the required Happy Hour charge headroom in the best "
                "known pre-event Agile slot(s)"
                if planned > _EPSILON
                else "Hold battery for the scheduled Weekend Happy Hour"
            ),
            "selected_slots": selected,
            "planned_battery_export_kwh": round(planned, 3),
            "next_export_slot": selected[0] if selected else None,
            "current_battery_export_target_kw": round(current_kw, 3),
            "normal_agile_export_suspended_until_happy_hour": True,
            "best_known_post_happy_hour_export_slot": context.get(
                "best_known_post_happy_hour_export_slot"
            ),
        }
    )
    return plan


def _active_happy_hour_routing(
    self, context: dict[str, Any], config: SimulationConfig
) -> dict[str, float]:
    """Return simple current routing for the focused graph during free charging."""
    house = _recent_house_load_kw(self)
    solar = _current_solar_kw(self, config)
    solar_home = min(house, solar)
    solar_export = min(
        max(solar - solar_home, 0.0),
        max(config.export_limit_kw, 0.0),
    )
    charge_kw = max(_number(context.get("charge_target_kw")) or 0.0, 0.0)
    grid_import = max(house - solar_home, 0.0) + charge_kw
    if config.site_import_limit_kw is not None:
        grid_import = min(grid_import, max(float(config.site_import_limit_kw), 0.0))
        charge_kw = max(grid_import - max(house - solar_home, 0.0), 0.0)
    return {
        "house_kw": round(house, 3),
        "solar_kw": round(solar, 3),
        "battery_net_kw": round(-charge_kw, 3),
        "grid_import_kw": round(grid_import, 3),
        "grid_export_kw": round(solar_export, 3),
    }


def improve_alpha743_dashboard(content: str) -> str:
    """Add compact event controls to the focused Alpha7.42 Agile page."""
    if _DASHBOARD_INSERT in content:
        return content
    if _DASHBOARD_MARKER not in content:
        raise ValueError("Alpha7.43 focused Agile dashboard marker missing")
    return content.replace(_DASHBOARD_MARKER, _DASHBOARD_INSERT, 1)


def install_alpha743_event_priority_patch() -> None:
    """Install Power Down priority, Happy Hour planning and dashboard controls."""
    manager_init = runtime.EfficientAgileSmartExportManager.__init__
    if not getattr(manager_init, "_kems_alpha743_event_priority", False):
        original_init = manager_init

        def init_with_alpha743(self, hass, entry_id, history_days):
            original_init(self, hass, entry_id, history_days)
            self._kems_alpha743_entry_id = entry_id

        init_with_alpha743._kems_alpha743_event_priority = True
        runtime.EfficientAgileSmartExportManager.__init__ = init_with_alpha743

    current_soc = rolling._current_agile_soc
    if not getattr(current_soc, "_kems_alpha743_event_priority", False):
        original_current_soc = current_soc

        def current_soc_with_alpha743(state):
            adjusted = _number(state.get("happy_hour_adjusted_soc_percent"))
            return adjusted if adjusted is not None else original_current_soc(state)

        current_soc_with_alpha743._kems_alpha743_event_priority = True
        rolling._current_agile_soc = current_soc_with_alpha743

    dispatch = alpha717._dispatch_targets
    if not getattr(dispatch, "_kems_alpha743_event_priority", False):
        original_dispatch = dispatch

        def dispatch_with_alpha743(
            self,
            state,
            plan,
            *,
            now,
            config: SimulationConfig,
            tariff: TariffSettings,
        ):
            targets = original_dispatch(
                self,
                state,
                plan,
                now=now,
                config=config,
                tariff=tariff,
            )
            power_down = _power_down_context(
                self,
                now=now,
                config=config,
                tariff=tariff,
            )
            if power_down.get("active"):
                active = _active_power_down_targets(self, state, power_down, config)
                targets.update(active)
                targets["event_priority_override"] = True
                return targets

            safe_plan = dict(plan) if isinstance(plan, dict) else {}
            safe_plan = _apply_power_down_to_plan(
                safe_plan,
                power_down,
                now=now,
            )
            safe_available = max(
                _number(safe_plan.get("exportable_battery_energy_kwh")) or 0.0,
                0.0,
            )
            happy = _happy_hour_context(
                self,
                state,
                now=now,
                config=config,
                tariff=tariff,
                power_down=power_down,
                safe_available_kwh=safe_available,
            )
            if happy.get("mode") == "charging":
                targets.update(
                    {
                        "mode": "happy_hour_charge",
                        "action": "Weekend Happy Hour — charge battery at maximum safe rate",
                        "house_battery_kw": 0.0,
                        "battery_export_target_kw": 0.0,
                        "battery_discharge_target_kw": 0.0,
                        "battery_charge_target_kw": happy.get("charge_target_kw"),
                        "happy_hour": happy,
                        "event_priority_override": True,
                    }
                )
                return targets

            if happy.get("mode") in {"preparation", "ready"} and happy.get(
                "preparation_in_current_horizon"
            ):
                selected = [
                    dict(item)
                    for item in happy.get("headroom_preparation_slots", [])
                    if isinstance(item, dict)
                ]
                export_kw = _selected_current_export_kw(selected, now)
                house_kw = max(_number(targets.get("house_battery_kw")) or 0.0, 0.0)
                export_kw = min(
                    max(export_kw, 0.0),
                    max(config.export_limit_kw, 0.0),
                    max(config.inverter_limit_kw - house_kw, 0.0),
                    max(config.max_discharge_kw - house_kw, 0.0),
                )
                targets.update(
                    {
                        "mode": (
                            "happy_hour_preparation"
                            if export_kw > _EPSILON
                            else "happy_hour_hold"
                        ),
                        "action": (
                            "Happy Hour preparation — export only the required "
                            "headroom in the best known pre-event Agile slot"
                            if export_kw > _EPSILON
                            else "Hold battery for the scheduled Weekend Happy Hour"
                        ),
                        "battery_export_target_kw": round(export_kw, 3),
                        "battery_discharge_target_kw": round(house_kw + export_kw, 3),
                        "happy_hour": happy,
                        "event_priority_override": True,
                    }
                )
                return targets

            if power_down.get("reserve_required_before_next_cheap"):
                selected = [
                    dict(item)
                    for item in safe_plan.get("selected_slots", [])
                    if isinstance(item, dict)
                ]
                allowed_kw = _selected_current_export_kw(selected, now)
                existing = max(
                    _number(targets.get("battery_export_target_kw")) or 0.0,
                    0.0,
                )
                export_kw = min(existing, allowed_kw)
                house_kw = max(_number(targets.get("house_battery_kw")) or 0.0, 0.0)
                targets.update(
                    {
                        "battery_export_target_kw": round(export_kw, 3),
                        "battery_discharge_target_kw": round(house_kw + export_kw, 3),
                        "power_down": power_down,
                        "power_down_price_override_blocked": True,
                    }
                )
            return targets

        dispatch_with_alpha743._kems_alpha743_event_priority = True
        alpha717._dispatch_targets = dispatch_with_alpha743

    rolling_plan = rolling._rolling_plan
    if not getattr(rolling_plan, "_kems_alpha743_event_priority", False):
        original_plan = rolling_plan

        def rolling_plan_with_alpha743(
            self,
            state,
            *,
            now,
            config: SimulationConfig,
            tariff: TariffSettings,
        ):
            plan = original_plan(self, state, now=now, config=config, tariff=tariff)
            if not isinstance(plan, dict):
                return plan
            power_down = _power_down_context(
                self,
                now=now,
                config=config,
                tariff=tariff,
            )
            _apply_power_down_to_plan(plan, power_down, now=now)
            safe_available = max(
                _number(plan.get("exportable_battery_energy_kwh")) or 0.0,
                0.0,
            )
            happy = _happy_hour_context(
                self,
                state,
                now=now,
                config=config,
                tariff=tariff,
                power_down=power_down,
                safe_available_kwh=safe_available,
            )
            _apply_happy_hour_to_plan(plan, happy, now=now)
            if power_down.get("active"):
                active = _active_power_down_targets(self, state, power_down, config)
                plan.update(
                    {
                        "dispatch_mode": active["mode"],
                        "dispatch_action": active["action"],
                        "current_house_battery_kw": active["house_battery_kw"],
                        "current_battery_discharge_target_kw": active[
                            "battery_discharge_target_kw"
                        ],
                        "current_battery_export_target_kw": active[
                            "battery_export_target_kw"
                        ],
                        "current_battery_charge_target_kw": 0.0,
                        "power_down_priority": power_down,
                    }
                )
            return plan

        rolling_plan_with_alpha743._kems_alpha743_event_priority = True
        rolling._rolling_plan = rolling_plan_with_alpha743

    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_alpha743_event_priority", False):
        original_publish = publish

        def publish_with_alpha743(self, state: dict[str, Any]) -> None:
            now = getattr(self, "_rolling_now", None)
            config = getattr(self, "_rolling_config", None)
            tariff = getattr(self, "_rolling_tariff", None)
            if not isinstance(now, datetime):
                now = _dt(state.get("generated_at"))
            if (
                isinstance(now, datetime)
                and isinstance(config, SimulationConfig)
                and isinstance(tariff, TariffSettings)
            ):
                power_down = _power_down_context(
                    self,
                    now=now,
                    config=config,
                    tariff=tariff,
                )
                happy = _happy_hour_context(
                    self,
                    state,
                    now=now,
                    config=config,
                    tariff=tariff,
                    power_down=power_down,
                )
                state["power_down_priority"] = power_down
                state["happy_hour_plan"] = happy
                corrected_soc = _corrected_happy_hour_soc(
                    self,
                    state,
                    happy,
                    now=now,
                    config=config,
                    power_down=power_down,
                )
                if corrected_soc is not None:
                    state["happy_hour_adjusted_soc_percent"] = corrected_soc
            else:
                power_down = {"available": False, "status": "Unavailable"}
                happy = {"available": False, "status": "Unavailable"}
                corrected_soc = None

            original_publish(self, state)

            rolling_state = self._hass.states.get(
                "sensor.kems_agile_rolling_export_plan"
            )
            rolling_attrs = (
                dict(rolling_state.attributes) if rolling_state is not None else {}
            )
            published_pd = rolling_attrs.get("power_down_priority")
            if isinstance(published_pd, dict):
                power_down = published_pd
            published_happy = rolling_attrs.get("happy_hour_plan")
            if isinstance(published_happy, dict):
                happy = published_happy

            self._set(
                _POWER_DOWN_SENSOR,
                power_down.get("status") or "No joined Power Down",
                {
                    "friendly_name": "Agile Power Down priority",
                    **power_down,
                },
            )
            self._set(
                _HAPPY_HOUR_SENSOR,
                happy.get("status") or "Disabled",
                {
                    "friendly_name": "Agile Weekend Happy Hour plan",
                    **happy,
                },
            )
            active_priority = (
                "Power Down"
                if power_down.get("active")
                else (
                    "Happy Hour"
                    if happy.get("mode") in {"charging", "preparation", "ready"}
                    else "Agile"
                )
            )
            self._set(
                _EVENT_PRIORITY_SENSOR,
                active_priority,
                {
                    "friendly_name": "Agile event priority",
                    "priority_order": "safety > Power Down > Happy Hour > Agile price",
                    "power_down": power_down,
                    "happy_hour": happy,
                    "hardware_writes": "blocked",
                },
            )

            if corrected_soc is not None:
                existing = self._hass.states.get(
                    "sensor.kems_agile_simulated_battery_soc_now"
                )
                attrs = dict(existing.attributes) if existing is not None else {}
                attrs.update(
                    {
                        "happy_hour_corrected": True,
                        "base_replay_soc_percent": _base_soc(state),
                        "happy_hour_plan": happy,
                        "hardware_writes": "blocked",
                    }
                )
                self._set(
                    "sensor.kems_agile_simulated_battery_soc_now",
                    round(corrected_soc, 2),
                    attrs,
                )

            if (
                isinstance(config, SimulationConfig)
                and happy.get("mode") == "charging"
                and not power_down.get("active")
            ):
                route = _active_happy_hour_routing(self, happy, config)
                overrides = {
                    "sensor.kems_agile_simulated_house_load_power": route["house_kw"],
                    "sensor.kems_agile_simulated_solar_power": route["solar_kw"],
                    "sensor.kems_agile_simulated_battery_net_power": route[
                        "battery_net_kw"
                    ],
                    "sensor.kems_agile_simulated_grid_import_power": route[
                        "grid_import_kw"
                    ],
                    "sensor.kems_agile_simulated_grid_export_power": route[
                        "grid_export_kw"
                    ],
                }
                for entity_id, value in overrides.items():
                    existing = self._hass.states.get(entity_id)
                    attrs = dict(existing.attributes) if existing is not None else {}
                    attrs.update(
                        {
                            "happy_hour_override": True,
                            "happy_hour_plan": happy,
                            "source": "Full KEMS Agile Happy Hour digital twin",
                            "hardware_writes": "blocked",
                        }
                    )
                    self._set(entity_id, value, attrs)

        publish_with_alpha743._kems_alpha743_event_priority = True
        runtime.EfficientAgileSmartExportManager._publish = publish_with_alpha743

    shutdown = runtime.EfficientAgileSmartExportManager.async_shutdown
    if not getattr(shutdown, "_kems_alpha743_event_priority", False):
        original_shutdown = shutdown

        async def shutdown_with_alpha743(self) -> None:
            await original_shutdown(self)
            for entity_id in _ALPHA743_SENSOR_IDS:
                self._hass.states.async_remove(entity_id)

        shutdown_with_alpha743._kems_alpha743_event_priority = True
        runtime.EfficientAgileSmartExportManager.async_shutdown = shutdown_with_alpha743

    from . import dashboard as dashboard_module

    combined = dashboard_module._combined_master_dashboard_bytes
    if not getattr(combined, "_kems_alpha743_event_priority", False):
        original_dashboard = combined

        def combined_alpha743_dashboard() -> bytes:
            content = original_dashboard().decode("utf-8")
            return improve_alpha743_dashboard(content).encode("utf-8")

        combined_alpha743_dashboard._kems_alpha743_event_priority = True
        dashboard_module._combined_master_dashboard_bytes = combined_alpha743_dashboard
