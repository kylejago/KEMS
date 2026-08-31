"""Canonical Alpha8 pre-cheap deadline integrity.

The frozen Alpha7.34 deadline runtime remains byte-identical regression evidence.
This Alpha8 layer accounts for a known Weekend Happy Hour in the physical
pre-cheap deadline model without weakening event priority: future free-charge
energy increases the discharge obligation, Happy Hour minutes are removed from
discharge capacity, and an active free charge is capped when necessary so KEMS
does not knowingly make the configured pre-cheap SOC target unreachable.

This remains simulation/shadow only. Real hardware writes stay blocked.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from . import agile_alpha717_dispatch as alpha717
from . import agile_rolling_replan as rolling
from .agile_deadline_guard import deadline_runtime
from .agile_event_priority import event_runtime as events
from .kems_core import SimulationConfig
from .tariff import TariffSettings

_EPSILON = 1e-6
_REACHABILITY_TOLERANCE_KWH = 0.05


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
    """Return one timezone-aware UTC timestamp when possible."""
    if isinstance(value, datetime):
        parsed = value
    elif value is not None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _happy_hour_deadline_context(
    self,
    *,
    now: datetime,
    deadline: datetime,
    config: SimulationConfig,
) -> dict[str, Any]:
    """Return remaining Happy Hour charge and blocked-discharge evidence."""
    try:
        event = events._happy_hour_event(self)
    except (AttributeError, TypeError, ValueError):
        return {"active": False, "reason": "Happy Hour unavailable"}

    if not isinstance(event, dict) or not event.get("enabled"):
        return {"active": False, "reason": "Happy Hour disabled"}

    start = _dt(event.get("start"))
    end = _dt(event.get("end"))
    if start is None or end is None or end <= start:
        return {"active": False, "reason": "Happy Hour window unavailable"}

    now_utc = now.astimezone(UTC)
    deadline_utc = deadline.astimezone(UTC)
    blocked_start = max(start, now_utc)
    blocked_end = min(end, deadline_utc)
    if blocked_end <= blocked_start:
        return {"active": False, "reason": "Happy Hour outside current deadline"}

    try:
        charge = events._happy_hour_charge_target(self, event, config)
    except (AttributeError, TypeError, ValueError):
        charge = {}

    charge_kw = max(_number(charge.get("charge_target_kw")) or 0.0, 0.0)
    blocked_hours = (blocked_end - blocked_start).total_seconds() / 3600.0
    stored_charge_kwh = charge_kw * blocked_hours * max(config.charge_efficiency, 0.01)
    discharge_obligation_kwh = stored_charge_kwh * max(
        config.discharge_efficiency, 0.01
    )
    return {
        "active": True,
        "active_now": start <= now_utc < end,
        "source": event.get("source"),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "blocked_start": blocked_start,
        "blocked_end": blocked_end,
        "blocked_hours": blocked_hours,
        "charge_target_kw": charge_kw,
        "remaining_stored_charge_kwh": stored_charge_kwh,
        "additional_discharge_obligation_kwh": discharge_obligation_kwh,
        "reason": (
            "Happy Hour blocks discharge and replenishes battery before cheap start"
        ),
    }


def _protected_capacity_segments(
    self,
    *,
    now: datetime,
    deadline: datetime,
    config: SimulationConfig,
    happy_hour: dict[str, Any],
) -> list[dict[str, Any]]:
    """Reuse Alpha7.34 capacity evidence but remove Happy Hour discharge time."""
    segments = deadline_runtime._capacity_segments(
        self,
        now=now,
        deadline=deadline,
        config=config,
    )
    blocked_start = happy_hour.get("blocked_start")
    blocked_end = happy_hour.get("blocked_end")
    if not isinstance(blocked_start, datetime) or not isinstance(blocked_end, datetime):
        return segments

    protected: list[dict[str, Any]] = []
    for segment in segments:
        start = segment.get("start")
        end = segment.get("end")
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            protected.append(dict(segment))
            continue

        boundaries = [start, end]
        for boundary in (blocked_start, blocked_end):
            if start < boundary < end:
                boundaries.append(boundary)
        boundaries.sort()

        for piece_start, piece_end in zip(boundaries, boundaries[1:], strict=False):
            midpoint = piece_start + (piece_end - piece_start) / 2
            blocked = blocked_start <= midpoint < blocked_end
            battery_kw = (
                0.0 if blocked else max(_number(segment.get("battery_kw")) or 0.0, 0.0)
            )
            hours = (piece_end - piece_start).total_seconds() / 3600.0
            piece = dict(segment)
            piece.update(
                {
                    "start": piece_start,
                    "end": piece_end,
                    "hours": hours,
                    "battery_kw": battery_kw,
                    "capacity_kwh": battery_kw * hours,
                    "happy_hour_blocked": blocked,
                }
            )
            if blocked:
                piece["basis"] = (
                    "Weekend Happy Hour event priority blocks battery discharge"
                )
            protected.append(piece)
    return protected


def _deadline_guard_context(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Extend the proven deadline guard only when Happy Hour affects this horizon."""
    baseline = deadline_runtime._deadline_guard_context(
        self,
        state,
        now=now,
        config=config,
        tariff=tariff,
    )
    if not isinstance(baseline, dict) or not baseline.get("available"):
        return baseline

    deadline = _dt(baseline.get("deadline"))
    if deadline is None:
        return baseline
    happy_hour = _happy_hour_deadline_context(
        self,
        now=now,
        deadline=deadline,
        config=config,
    )
    if not happy_hour.get("active"):
        return baseline

    now_utc = now.astimezone(UTC)
    current_required_ac = max(
        _number(baseline.get("required_discharge_kwh")) or 0.0,
        0.0,
    )
    happy_hour_obligation = max(
        _number(happy_hour.get("additional_discharge_obligation_kwh")) or 0.0,
        0.0,
    )
    happy_hour_stored_charge = max(
        _number(happy_hour.get("remaining_stored_charge_kwh")) or 0.0,
        0.0,
    )
    required_ac = current_required_ac + happy_hour_obligation
    segments = _protected_capacity_segments(
        self,
        now=now,
        deadline=deadline,
        config=config,
        happy_hour=happy_hour,
    )
    remaining_capacity = sum(
        max(_number(item.get("capacity_kwh")) or 0.0, 0.0) for item in segments
    )
    margin = remaining_capacity - required_ac
    latest_safe = deadline_runtime._latest_safe_start(segments, required_ac)
    guarded_start = (
        latest_safe - timedelta(minutes=deadline_runtime.DEADLINE_GUARD_MINUTES)
        if latest_safe is not None
        else now_utc
    )
    reachable = remaining_capacity + _REACHABILITY_TOLERANCE_KWH >= required_ac

    if required_ac <= 0.01:
        mode = "target_reached"
    elif not reachable:
        mode = "maximum_discharge"
    elif now_utc >= guarded_start:
        mode = "deadline_following"
    else:
        mode = "price_optimised"

    hours = max((deadline - now_utc).total_seconds() / 3600.0, _EPSILON)
    current_battery_headroom = (
        max(_number(segments[0].get("battery_kw")) or 0.0, 0.0)
        if segments
        else max(_number(baseline.get("current_battery_headroom_kw")) or 0.0, 0.0)
    )
    effective_kw = max(
        _number(deadline_runtime._effective_deadline_kw(config)) or 0.0,
        0.0,
    )
    skippable_half_hours = max(
        math.floor(max(margin, 0.0) / max(effective_kw * 0.5, 0.001)),
        0,
    )

    capacity = max(config.battery_capacity_kwh, 0.1)
    efficiency = max(config.discharge_efficiency, 0.01)
    soc = _number(baseline.get("simulated_soc_percent"))
    battery_kwh = (
        capacity * min(max(soc, 0.0), 100.0) / 100.0 if soc is not None else 0.0
    )
    maximum_stored_discharge = remaining_capacity / efficiency
    projected_battery_kwh = min(battery_kwh + happy_hour_stored_charge, capacity)
    target_soc = _number(baseline.get("target_soc_percent")) or 0.0
    minimum_reachable_soc = max(
        (projected_battery_kwh - maximum_stored_discharge) / capacity * 100.0,
        target_soc if reachable else 0.0,
    )
    minimum_reachable_soc = min(max(minimum_reachable_soc, 0.0), 100.0)

    protected = dict(baseline)
    protected.update(
        {
            "mode": mode,
            "current_soc_required_discharge_kwh": round(current_required_ac, 3),
            "required_discharge_kwh": round(required_ac, 3),
            "solar_aware_remaining_capacity_kwh": round(remaining_capacity, 3),
            "solar_aware_deadline_margin_kwh": round(margin, 3),
            "minimum_reachable_soc_percent": round(minimum_reachable_soc, 2),
            "target_physically_reachable_now": reachable,
            "latest_safe_export_start": (
                latest_safe.isoformat() if latest_safe is not None else None
            ),
            "guarded_latest_safe_export_start": guarded_start.isoformat(),
            "deadline_guard_active": mode
            in {"deadline_following", "maximum_discharge"},
            "current_battery_headroom_kw": round(current_battery_headroom, 3),
            "required_average_discharge_kw": round(required_ac / hours, 3),
            "skippable_half_hours": skippable_half_hours,
            "capacity_model": (
                "5-minute solar-aware shared-inverter headroom; Happy Hour "
                "charge/discharge window protected"
            ),
            "forecast_solar_used": any(
                item.get("basis") == "KEMS hourly solar forecast" for item in segments
            ),
            "happy_hour_deadline_protected": True,
            "happy_hour_active_now": bool(happy_hour.get("active_now")),
            "happy_hour_deadline_obligation_kwh": round(happy_hour_obligation, 3),
            "happy_hour_discharge_blocked_hours": round(
                max(_number(happy_hour.get("blocked_hours")) or 0.0, 0.0),
                3,
            ),
            "happy_hour_deadline_context": {
                key: value
                for key, value in happy_hour.items()
                if key not in {"blocked_start", "blocked_end"}
            },
        }
    )
    return protected


def _active_happy_hour_charge_cap(
    guard: dict[str, Any],
    *,
    config: SimulationConfig,
) -> dict[str, Any]:
    """Cap remaining free charging to energy that can still be cleared afterward."""
    context = guard.get("happy_hour_deadline_context")
    context = dict(context) if isinstance(context, dict) else {}
    requested_kw = max(_number(context.get("charge_target_kw")) or 0.0, 0.0)
    remaining_hours = max(
        _number(context.get("blocked_hours"))
        or _number(guard.get("happy_hour_discharge_blocked_hours"))
        or 0.0,
        0.0,
    )
    current_required = max(
        _number(guard.get("current_soc_required_discharge_kwh")) or 0.0,
        0.0,
    )
    post_event_capacity = max(
        _number(guard.get("solar_aware_remaining_capacity_kwh")) or 0.0,
        0.0,
    )
    safe_extra_ac = max(post_event_capacity - current_required, 0.0)
    round_trip = max(config.charge_efficiency, 0.01) * max(
        config.discharge_efficiency, 0.01
    )
    if remaining_hours <= _EPSILON:
        safe_kw = 0.0
    else:
        safe_kw = safe_extra_ac / (remaining_hours * round_trip)
    safe_kw = min(requested_kw, max(safe_kw, 0.0))
    limited = safe_kw + _EPSILON < requested_kw
    bounded_obligation = safe_kw * remaining_hours * round_trip
    reachable_with_bound = (
        current_required + bounded_obligation
        <= post_event_capacity + _REACHABILITY_TOLERANCE_KWH
    )
    return {
        "requested_charge_kw": round(requested_kw, 3),
        "safe_charge_kw": round(safe_kw, 3),
        "limited": limited,
        "remaining_event_hours": round(remaining_hours, 3),
        "current_soc_required_discharge_kwh": round(current_required, 3),
        "post_event_discharge_capacity_kwh": round(post_event_capacity, 3),
        "safe_additional_discharge_obligation_kwh": round(safe_extra_ac, 3),
        "bounded_additional_discharge_obligation_kwh": round(bounded_obligation, 3),
        "target_reachable_with_bounded_charge": reachable_with_bound,
        "reason": (
            "Happy Hour charge capped to preserve pre-cheap SOC recoverability"
            if limited
            else "full Happy Hour charge remains recoverable before cheap start"
        ),
    }


def _apply_active_happy_hour_cap(
    targets: dict[str, Any],
    guard: dict[str, Any],
    *,
    config: SimulationConfig,
) -> dict[str, Any]:
    """Preserve Happy Hour priority while applying the physical deadline cap."""
    cap = _active_happy_hour_charge_cap(guard, config=config)
    safe_kw = max(_number(cap.get("safe_charge_kw")) or 0.0, 0.0)
    happy = targets.get("happy_hour")
    happy = dict(happy) if isinstance(happy, dict) else {}
    happy.update(
        {
            "requested_charge_target_kw": cap["requested_charge_kw"],
            "charge_target_kw": cap["safe_charge_kw"],
            "deadline_safe_charge_target_kw": cap["safe_charge_kw"],
            "deadline_charge_limited": cap["limited"],
            "deadline_integrity": cap,
        }
    )
    targets.update(
        {
            "mode": "happy_hour_charge",
            "battery_export_target_kw": 0.0,
            "battery_discharge_target_kw": 0.0,
            "battery_charge_target_kw": round(safe_kw, 3),
            "happy_hour": happy,
            "event_priority_override": True,
            "deadline_integrity_override": bool(cap["limited"]),
            "deadline_safe_happy_hour_charge_kw": round(safe_kw, 3),
            "happy_hour_charge_limited_by_deadline": bool(cap["limited"]),
        }
    )
    if cap["limited"]:
        targets["action"] = (
            "Weekend Happy Hour — deadline-safe free-grid charge capped to "
            f"{safe_kw:.2f} kW"
        )
    guard["active_happy_hour_charge_cap"] = cap
    guard["target_physically_reachable_with_bounded_happy_hour"] = bool(
        cap["target_reachable_with_bounded_charge"]
    )
    targets["deadline_guard"] = guard
    return targets


def _apply_deadline_discharge(
    targets: dict[str, Any],
    guard: dict[str, Any],
    *,
    config: SimulationConfig,
) -> dict[str, Any]:
    """Make the Happy-Hour-aware guard dominate only when the deadline requires it."""
    guard_mode = str(guard.get("mode") or "price_optimised")
    if guard_mode not in {"deadline_following", "maximum_discharge"}:
        return targets
    if str(targets.get("mode") or "") == "power_down_session":
        return targets

    evidence = targets.get("solar_aware_inverter_headroom")
    evidence = dict(evidence) if isinstance(evidence, dict) else {}
    safe_battery_kw = _number(evidence.get("battery_inverter_headroom_kw"))
    if safe_battery_kw is None:
        safe_battery_kw = _number(guard.get("current_battery_headroom_kw"))
    safe_battery_kw = min(
        max(safe_battery_kw or 0.0, 0.0),
        max(config.max_discharge_kw, 0.0),
    )
    house_kw = min(
        max(_number(targets.get("house_battery_kw")) or 0.0, 0.0),
        safe_battery_kw,
    )
    export_kw = min(
        max(safe_battery_kw - house_kw, 0.0),
        max(config.export_limit_kw, 0.0),
        max(config.inverter_limit_kw - house_kw, 0.0),
        max(config.max_discharge_kw - house_kw, 0.0),
    )
    total_kw = house_kw + export_kw
    previous_mode = str(targets.get("mode") or "price_optimised")
    action = (
        "maximum discharge — Happy Hour-adjusted pre-cheap target is physically "
        "unreachable; house first"
        if guard_mode == "maximum_discharge"
        else "deadline guard active — export pulled earlier for scheduled Happy "
        "Hour; house first"
    )
    targets.update(
        {
            "mode": guard_mode,
            "action": action,
            "house_battery_kw": round(house_kw, 3),
            "battery_export_target_kw": round(export_kw, 3),
            "battery_discharge_target_kw": round(total_kw, 3),
            "battery_charge_target_kw": 0.0,
            "deadline_margin_kwh": guard.get("solar_aware_deadline_margin_kwh"),
            "required_average_kw": guard.get("required_average_discharge_kw"),
            "deadline_guard_escalated_from": previous_mode,
            "deadline_integrity_override": True,
            "happy_hour_deadline_override": True,
            "deadline_guard": guard,
        }
    )
    if evidence:
        evidence.update(
            {
                "deadline_guard_applied": True,
                "permitted_battery_to_home_kw": round(house_kw, 3),
                "permitted_battery_export_kw": round(export_kw, 3),
                "permitted_total_discharge_kw": round(total_kw, 3),
                "happy_hour_deadline_override": True,
            }
        )
        targets["solar_aware_inverter_headroom"] = evidence
    return targets


def _publish_guard_to_plan(
    plan: dict[str, Any],
    guard: dict[str, Any],
    *,
    config: SimulationConfig,
) -> dict[str, Any]:
    """Publish the corrected physical guard and active Happy Hour charge cap."""
    plan["deadline_guard"] = dict(guard)
    for key in (
        "latest_safe_export_start",
        "guarded_latest_safe_export_start",
        "deadline_guard_active",
        "deadline_guard_minutes",
        "target_physically_reachable_now",
        "solar_aware_remaining_capacity_kwh",
        "solar_aware_deadline_margin_kwh",
        "minimum_reachable_soc_percent",
        "skippable_half_hours",
        "capacity_model",
        "forecast_solar_used",
        "happy_hour_deadline_protected",
        "happy_hour_deadline_obligation_kwh",
        "happy_hour_discharge_blocked_hours",
    ):
        plan[key] = guard.get(key)

    if guard.get("happy_hour_active_now"):
        cap = _active_happy_hour_charge_cap(guard, config=config)
        plan["current_battery_charge_target_kw"] = cap["safe_charge_kw"]
        plan["deadline_safe_happy_hour_charge_kw"] = cap["safe_charge_kw"]
        plan["happy_hour_charge_limited_by_deadline"] = cap["limited"]
        happy = plan.get("happy_hour_plan")
        happy = dict(happy) if isinstance(happy, dict) else {}
        happy.update(
            {
                "requested_charge_target_kw": cap["requested_charge_kw"],
                "charge_target_kw": cap["safe_charge_kw"],
                "deadline_safe_charge_target_kw": cap["safe_charge_kw"],
                "deadline_charge_limited": cap["limited"],
                "deadline_integrity": cap,
            }
        )
        plan["happy_hour_plan"] = happy
        guard["active_happy_hour_charge_cap"] = cap
        guard["target_physically_reachable_with_bounded_happy_hour"] = bool(
            cap["target_reachable_with_bounded_charge"]
        )
        plan["deadline_guard"] = dict(guard)
    return plan


def install_deadline_integrity() -> None:
    """Install Alpha8 deadline integrity outside the frozen Alpha7 boundary."""
    dispatch = alpha717._dispatch_targets
    if not getattr(dispatch, "_kems_deadline_integrity", False):
        original_dispatch = dispatch

        def dispatch_with_deadline_integrity(
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
            if not isinstance(targets, dict):
                return targets
            guard = _deadline_guard_context(
                self,
                state,
                now=now,
                config=config,
                tariff=tariff,
            )
            self._kems_alpha863_deadline_guard = dict(guard)
            self._kems_alpha734_deadline_guard = dict(guard)
            targets["deadline_guard"] = dict(guard)
            if not guard.get("happy_hour_deadline_protected"):
                return targets
            if (
                guard.get("happy_hour_active_now")
                and str(targets.get("mode") or "") == "happy_hour_charge"
            ):
                return _apply_active_happy_hour_cap(
                    targets,
                    guard,
                    config=config,
                )
            return _apply_deadline_discharge(
                targets,
                guard,
                config=config,
            )

        dispatch_with_deadline_integrity._kems_deadline_integrity = True
        alpha717._dispatch_targets = dispatch_with_deadline_integrity

    rolling_plan = rolling._rolling_plan
    if not getattr(rolling_plan, "_kems_deadline_integrity", False):
        original_plan = rolling_plan

        def rolling_plan_with_deadline_integrity(
            self,
            state,
            *,
            now,
            config: SimulationConfig,
            tariff: TariffSettings,
        ):
            plan = original_plan(
                self,
                state,
                now=now,
                config=config,
                tariff=tariff,
            )
            if not isinstance(plan, dict):
                return plan
            guard = _deadline_guard_context(
                self,
                state,
                now=now,
                config=config,
                tariff=tariff,
            )
            self._kems_alpha863_deadline_guard = dict(guard)
            self._kems_alpha734_deadline_guard = dict(guard)
            if guard.get("happy_hour_deadline_protected"):
                _publish_guard_to_plan(plan, guard, config=config)
            return plan

        rolling_plan_with_deadline_integrity._kems_deadline_integrity = True
        rolling._rolling_plan = rolling_plan_with_deadline_integrity
