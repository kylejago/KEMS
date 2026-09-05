"""Strict per-reward-hour Weekend Happy Hour budgeting.

Each Octopus Happy Hour reward owns an independent 16 kWh import bucket.
Unused allowance never carries into the next reward hour and future reward
allowance can never be borrowed early. Battery charging is reserved first,
unavoidable home import is protected next, and the EV may use only the
remaining allowance. Once the current reward-hour cap is exhausted KEMS
immediately falls back to the normal tariff/dispatch logic.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from .happy_hour import HAPPY_HOUR_FAIR_USE_KWH_PER_REWARD

_EPSILON = 1e-6
_MAX_LEDGER_GAP = timedelta(minutes=10)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def reward_hour_windows(
    start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    """Return independent one-hour reward windows, capped at two rewards."""
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    windows: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end and len(windows) < 2:
        window_end = min(cursor + timedelta(hours=1), end)
        windows.append((cursor, window_end))
        cursor = window_end
    return windows


def integrate_power_kwh(
    records: Iterable[Any],
    *,
    start: datetime,
    end: datetime,
    field: str,
    cap_kwh: float | None = None,
) -> tuple[float, bool, datetime | None]:
    """Integrate one observed kW field and report ledger coverage/cap time."""
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    if end <= start:
        return 0.0, True, None

    samples: list[tuple[datetime, float]] = []
    for record in records:
        timestamp = _dt(getattr(record, "timestamp", None))
        power = _number(getattr(record, field, None))
        if timestamp is None or power is None:
            continue
        samples.append((timestamp, max(power, 0.0)))
    samples.sort(key=lambda item: item[0])
    if not samples:
        return 0.0, False, None

    seed = next((item for item in reversed(samples) if item[0] <= start), None)
    coverage = bool(seed is not None and start - seed[0] <= _MAX_LEDGER_GAP)
    if seed is not None:
        cursor = start
        current_power = seed[1]
    else:
        first = next((item for item in samples if start < item[0] <= end), None)
        if first is None:
            return 0.0, False, None
        cursor = first[0]
        current_power = first[1]

    energy = 0.0
    cap_at: datetime | None = None
    for timestamp, power in samples:
        if timestamp <= cursor or timestamp <= start:
            continue
        if timestamp > end:
            break
        gap = timestamp - cursor
        if gap > _MAX_LEDGER_GAP:
            coverage = False
        increment = current_power * gap.total_seconds() / 3600.0
        if (
            cap_kwh is not None
            and cap_at is None
            and current_power > _EPSILON
            and energy + increment >= cap_kwh
        ):
            cap_at = cursor + timedelta(
                hours=max(cap_kwh - energy, 0.0) / current_power
            )
        energy += increment
        cursor = timestamp
        current_power = power

    if cursor < end:
        gap = end - cursor
        if gap > _MAX_LEDGER_GAP:
            coverage = False
        increment = current_power * gap.total_seconds() / 3600.0
        if (
            cap_kwh is not None
            and cap_at is None
            and current_power > _EPSILON
            and energy + increment >= cap_kwh
        ):
            cap_at = cursor + timedelta(
                hours=max(cap_kwh - energy, 0.0) / current_power
            )
        energy += increment

    return round(max(energy, 0.0), 4), coverage, cap_at


def reward_hour_ledger(
    records: Iterable[Any],
    *,
    start: datetime,
    end: datetime,
    now: datetime,
) -> list[dict[str, Any]]:
    """Return independent 16 kWh ledgers; allowance is never pooled."""
    now_utc = now.astimezone(UTC)
    output: list[dict[str, Any]] = []
    cap = float(HAPPY_HOUR_FAIR_USE_KWH_PER_REWARD)
    for index, (bucket_start, bucket_end) in enumerate(
        reward_hour_windows(start, end), start=1
    ):
        cutoff = min(max(now_utc, bucket_start), bucket_end)
        if cutoff <= bucket_start:
            used, coverage, cap_at = 0.0, False, None
        else:
            used, coverage, cap_at = integrate_power_kwh(
                records,
                start=bucket_start,
                end=cutoff,
                field="grid_import_kw",
                cap_kwh=cap,
            )
        cap_reached = used >= cap - 0.001
        authority_end = (
            cap_at
            if coverage and cap_at is not None
            else cutoff if coverage else bucket_start
        )
        output.append(
            {
                "index": index,
                "start": bucket_start.isoformat(),
                "end": bucket_end.isoformat(),
                "cap_kwh": cap,
                "import_kwh": round(used, 3),
                "remaining_kwh": round(max(cap - used, 0.0), 3),
                "coverage_complete": coverage,
                "cap_reached": cap_reached,
                "cap_reached_at": cap_at.isoformat() if cap_at else None,
                "authority_end": authority_end.isoformat(),
                "authority_duration_hours": round(
                    max(
                        (authority_end - bucket_start).total_seconds() / 3600.0,
                        0.0,
                    ),
                    4,
                ),
            }
        )
    return output


def allocate_reward_hour(
    *,
    remaining_kwh: float,
    hours_remaining: float,
    home_grid_kw: float,
    battery_headroom_stored_kwh: float,
    charge_efficiency: float,
    max_charge_kw: float,
    inverter_limit_kw: float,
    site_import_limit_kw: float | None,
) -> dict[str, float]:
    """Reserve battery first, home next, then expose only EV remainder."""
    remaining = max(float(remaining_kwh), 0.0)
    hours = max(float(hours_remaining), 0.0)
    home_kw = max(float(home_grid_kw), 0.0)
    efficiency = max(float(charge_efficiency), 0.01)
    projected_home = min(home_kw * hours, remaining)

    battery_power_limit = min(
        max(float(max_charge_kw), 0.0),
        max(float(inverter_limit_kw), 0.0),
    )
    if site_import_limit_kw is not None and float(site_import_limit_kw) > 0:
        battery_power_limit = min(
            battery_power_limit,
            max(float(site_import_limit_kw) - home_kw, 0.0),
        )
    battery_input_headroom = max(float(battery_headroom_stored_kwh), 0.0) / efficiency
    battery_max_input = min(
        battery_input_headroom,
        battery_power_limit * hours,
    )
    battery_reserved = min(
        battery_max_input,
        max(remaining - projected_home, 0.0),
    )
    battery_target_kw = (
        min(battery_power_limit, battery_reserved / hours) if hours > _EPSILON else 0.0
    )
    ev_allowance = max(
        remaining - projected_home - battery_reserved,
        0.0,
    )
    return {
        "projected_home_import_kwh_remaining": round(projected_home, 3),
        "battery_reserved_input_kwh_remaining": round(battery_reserved, 3),
        "battery_charge_target_kw": round(battery_target_kw, 3),
        "ev_allowance_kwh_remaining": round(ev_allowance, 3),
    }


def _latest_record(self: Any, now: datetime) -> Any | None:
    records = list(getattr(self, "_panel_today_records", []) or [])
    now_utc = now.astimezone(UTC)
    candidates = [
        record
        for record in records
        if (_dt(getattr(record, "timestamp", None)) or now_utc) <= now_utc
    ]
    return candidates[-1] if candidates else (records[-1] if records else None)


def _home_grid_kw(
    self: Any, context: dict[str, Any], now: datetime
) -> tuple[float, float, float, float]:
    latest = _latest_record(self, now)
    house = _number(getattr(latest, "house_load_kw", None)) if latest else None
    ev = _number(getattr(latest, "ev_power_kw", None)) if latest else None
    solar = _number(getattr(latest, "solar_power_kw", None)) if latest else None
    grid = _number(getattr(latest, "grid_import_kw", None)) if latest else None
    if house is None:
        house = _number(context.get("expected_house_import_kw")) or 0.0
    ev = max(ev or 0.0, 0.0)
    solar = max(solar or 0.0, 0.0)
    non_ev_house = max(house - ev, 0.0)
    home_grid = max(non_ev_house - solar, 0.0)
    return home_grid, max(house, 0.0), ev, max(grid or 0.0, 0.0)


def _adjusted_headroom(
    state: dict[str, Any], context: dict[str, Any], config: Any
) -> float:
    capacity = max(float(config.battery_capacity_kwh), 0.1)
    soc = _number(state.get("happy_hour_adjusted_soc_percent"))
    if soc is None:
        soc = _number(context.get("current_simulated_soc_percent"))
    if soc is not None:
        return capacity * (100.0 - min(max(soc, 0.0), 100.0)) / 100.0
    return max(_number(context.get("current_battery_headroom_kwh")) or 0.0, 0.0)


def decorate_happy_hour_context(
    self: Any,
    state: dict[str, Any],
    context: dict[str, Any],
    *,
    now: datetime,
    config: Any,
    power_down: dict[str, Any],
) -> dict[str, Any]:
    """Attach the strict hourly ledger and current battery/EV allocation."""
    start = _dt(context.get("start"))
    end = _dt(context.get("end"))
    if start is None or end is None or end <= start:
        return context
    records = list(getattr(self, "_panel_today_records", []) or [])
    ledgers = reward_hour_ledger(records, start=start, end=end, now=now)
    context["reward_cap_kwh_per_hour"] = float(HAPPY_HOUR_FAIR_USE_KWH_PER_REWARD)
    context["reward_hour_count"] = len(ledgers)
    context["reward_hours"] = ledgers
    context["reward_allowance_is_pooled"] = False
    context["unused_reward_allowance_carries_forward"] = False
    context["future_reward_allowance_can_be_borrowed"] = False
    context["base_happy_hour_charge_target_kw"] = max(
        _number(context.get("charge_target_kw")) or 0.0, 0.0
    )

    now_utc = now.astimezone(UTC)
    current = next(
        (
            item
            for item in ledgers
            if (_dt(item["start"]) or start) <= now_utc < (_dt(item["end"]) or end)
        ),
        None,
    )
    if current is None:
        context["happy_hour_import_authority_active"] = False
        context["ev_happy_hour_allowed"] = False
        return context

    bucket_end = _dt(current["end"]) or end
    hours_remaining = max((bucket_end - now_utc).total_seconds() / 3600.0, 0.0)
    home_grid_kw, house_kw, ev_kw, observed_grid_kw = _home_grid_kw(self, context, now)
    allocation = allocate_reward_hour(
        remaining_kwh=float(current["remaining_kwh"]),
        hours_remaining=hours_remaining,
        home_grid_kw=home_grid_kw,
        battery_headroom_stored_kwh=_adjusted_headroom(state, context, config),
        charge_efficiency=float(config.charge_efficiency),
        max_charge_kw=float(config.max_charge_kw),
        inverter_limit_kw=float(config.inverter_limit_kw),
        site_import_limit_kw=config.site_import_limit_kw,
    )
    context.update(
        {
            "current_reward_hour_index": int(current["index"]),
            "current_reward_hour_start": current["start"],
            "current_reward_hour_end": current["end"],
            "current_reward_hour_import_kwh": current["import_kwh"],
            "current_reward_hour_remaining_kwh": current["remaining_kwh"],
            "current_reward_hour_cap_reached": current["cap_reached"],
            "current_reward_hour_ledger_complete": current["coverage_complete"],
            "current_reward_hour_cap_reached_at": current["cap_reached_at"],
            "hours_remaining_in_reward_hour": round(hours_remaining, 4),
            "projected_non_ev_home_grid_kw": round(home_grid_kw, 3),
            "observed_house_load_kw": round(house_kw, 3),
            "observed_ev_power_kw": round(ev_kw, 3),
            "observed_grid_import_kw": round(observed_grid_kw, 3),
            **allocation,
        }
    )

    if power_down.get("active") or context.get("mode") == "power_down_override":
        context["happy_hour_import_authority_active"] = False
        context["ev_happy_hour_allowed"] = False
        return context

    if not current["coverage_complete"]:
        context.update(
            {
                "mode": "budget_wait",
                "status": (
                    "Waiting for a complete reward-hour import ledger — "
                    "normal tariff logic"
                ),
                "charge_target_kw": 0.0,
                "happy_hour_import_authority_active": False,
                "ev_happy_hour_allowed": False,
            }
        )
        return context

    if current["cap_reached"]:
        context.update(
            {
                "mode": "cap_reached",
                "status": (
                    f"Reward hour {current['index']} reached 16 kWh — "
                    "normal tariff logic"
                ),
                "charge_target_kw": 0.0,
                "happy_hour_import_authority_active": False,
                "ev_happy_hour_allowed": False,
            }
        )
        return context

    context.update(
        {
            "mode": "charging",
            "charge_target_kw": allocation["battery_charge_target_kw"],
            "happy_hour_import_authority_active": True,
            "ev_happy_hour_allowed": (allocation["ev_allowance_kwh_remaining"] > 0.10),
            "status": (
                f"Reward hour {current['index']}: "
                f"{float(current['remaining_kwh']):.2f} kWh remaining; "
                f"battery {allocation['battery_charge_target_kw']:.2f} kW first"
            ),
        }
    )
    return context


def _corrected_soc_with_hourly_budget(
    runtime: Any,
    self: Any,
    state: dict[str, Any],
    context: dict[str, Any],
    *,
    now: datetime,
    config: Any,
    power_down: dict[str, Any],
) -> float | None:
    """Correct SOC only across reward-hour intervals with free-import authority."""
    base_soc = runtime._base_soc(state)
    start = _dt(context.get("start"))
    if base_soc is None or start is None or now.astimezone(UTC) < start:
        return None
    if context.get("power_down_overlap") and power_down.get("active"):
        return None

    intervals: list[tuple[datetime, datetime]] = []
    for bucket in context.get("reward_hours", []):
        if not isinstance(bucket, dict) or not bucket.get("coverage_complete"):
            continue
        bucket_start = _dt(bucket.get("start"))
        authority_end = _dt(bucket.get("authority_end"))
        if (
            bucket_start is None
            or authority_end is None
            or authority_end <= bucket_start
        ):
            continue
        intervals.append((bucket_start, authority_end))
    if not intervals:
        return None

    active_hours = sum(
        (finish - begin).total_seconds() / 3600.0 for begin, finish in intervals
    )
    charge_kw = max(
        _number(context.get("base_happy_hour_charge_target_kw")) or 0.0,
        0.0,
    )
    free_stored = charge_kw * active_hours * max(float(config.charge_efficiency), 0.01)

    replay_discharge_ac = 0.0
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        slot_start = _dt(slot.get("valid_from"))
        slot_end = _dt(slot.get("valid_to"))
        if slot_start is None or slot_end is None or slot_end <= slot_start:
            continue
        slot_hours = (slot_end - slot_start).total_seconds() / 3600.0
        overlap = 0.0
        for begin, finish in intervals:
            overlap += max(
                (min(slot_end, finish) - max(slot_start, begin)).total_seconds()
                / 3600.0,
                0.0,
            )
        if overlap <= _EPSILON:
            continue
        fraction = min(overlap / max(slot_hours, _EPSILON), 1.0)
        replay_discharge_ac += fraction * max(
            _number(slot.get("battery_to_home_kwh")) or 0.0, 0.0
        )
        replay_discharge_ac += fraction * max(
            _number(slot.get("battery_export_kwh")) or 0.0, 0.0
        )

    capacity = max(float(config.battery_capacity_kwh), 0.1)
    base_stored = capacity * min(max(base_soc, 0.0), 100.0) / 100.0
    corrected = min(
        base_stored
        + replay_discharge_ac / max(float(config.discharge_efficiency), 0.01)
        + free_stored,
        capacity,
    )
    return round(100.0 * corrected / capacity, 2)


def apply_happy_hour_control(control: Any, snapshot: Any, context: dict[str, Any]):
    """Overlay Happy Hour EV permission without widening normal cheap authority."""
    if not context.get("happy_hour_import_authority_active"):
        return control
    ev_allowed = bool(
        getattr(snapshot, "ev_connected", False)
        and context.get("ev_happy_hour_allowed")
    )
    return replace(
        control,
        operating_reason="happy_hour_reward_hour",
        desired_charge_power_kw=max(
            _number(context.get("charge_target_kw")) or 0.0, 0.0
        ),
        desired_ev_charging_allowed=ev_allowed,
        desired_battery_to_home_power_kw=0.0,
        desired_battery_export_power_kw=0.0,
        desired_total_discharge_power_kw=0.0,
        desired_grid_export_allowed=False,
    )


def install_happy_hour_budget() -> None:
    """Install strict hourly budgeting after automatic/retained HH discovery."""
    from . import agile_event_priority_runtime as runtime

    original_context = runtime._happy_hour_context
    if getattr(original_context, "_kems_hourly_happy_hour_budget", False):
        return

    def context_with_hourly_budget(
        self,
        state,
        *,
        now,
        config,
        tariff,
        power_down,
        safe_available_kwh=None,
    ):
        context = original_context(
            self,
            state,
            now=now,
            config=config,
            tariff=tariff,
            power_down=power_down,
            safe_available_kwh=safe_available_kwh,
        )
        return decorate_happy_hour_context(
            self,
            state,
            context,
            now=now,
            config=config,
            power_down=power_down,
        )

    context_with_hourly_budget._kems_hourly_happy_hour_budget = True
    runtime._happy_hour_context = context_with_hourly_budget

    original_corrected = runtime._corrected_happy_hour_soc

    def corrected_with_hourly_budget(
        self,
        state,
        context,
        *,
        now,
        config,
        power_down,
    ):
        if context.get("reward_hours"):
            return _corrected_soc_with_hourly_budget(
                runtime,
                self,
                state,
                context,
                now=now,
                config=config,
                power_down=power_down,
            )
        return original_corrected(
            self,
            state,
            context,
            now=now,
            config=config,
            power_down=power_down,
        )

    corrected_with_hourly_budget._kems_hourly_happy_hour_budget = True
    runtime._corrected_happy_hour_soc = corrected_with_hourly_budget
