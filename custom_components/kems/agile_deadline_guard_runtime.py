"""Alpha 7.34 latest-safe-start guard for Agile Smart Export.

Alpha7.31 proved exact candidate/replay parity and the shared 7 kW AC constraint.
Alpha7.34 keeps that proven routing but prevents price optimisation from waiting
past the point where the configured pre-cheap SOC target can still be reached.

The guard works backwards from the next configured overnight cheap start.  It
integrates the remaining battery AC headroom in five-minute segments, derating
that headroom for forecast/proposal solar because Feed-in First gives solar the
shared inverter first.  Price optimisation remains active while there is slack;
inside a ten-minute guard before the latest safe start KEMS requests the full
safe battery path.  If the target is already physically unreachable, the
existing maximum-discharge failsafe remains in charge.

Weekend Happy Hour is part of the physical deadline model.  A known Happy Hour
blocks battery discharge while the free-charge event is active and its remaining
stored charge is treated as energy that must be discharged again before the
pre-cheap target.  That moves the latest-safe export start earlier instead of
allowing a late free charge to make the target physically unreachable.

This remains simulation/shadow only.  Real hardware writes are still gated by
commissioning and the hardware backend.
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
from .agile_deadline_dispatch import _effective_deadline_kw, _target_percent
from .kems_core import SimulationConfig
from .tariff import TariffSettings

DEADLINE_GUARD_MINUTES = 10
CAPACITY_STEP_MINUTES = 5
_EPSILON = 1e-6


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


def _forecast_solar_kw(self, moment: datetime) -> float | None:
    """Return forecast average solar kW for the hour containing ``moment``."""
    forecast = getattr(self, "_kems_alpha734_forecast", None)
    hourly = getattr(forecast, "hourly", ()) if forecast is not None else ()
    moment_utc = moment.astimezone(UTC)
    for item in hourly or ():
        timestamp = getattr(item, "timestamp", None)
        energy = _number(getattr(item, "solar_energy_kwh", None))
        if not isinstance(timestamp, datetime) or energy is None:
            continue
        start = timestamp.astimezone(UTC)
        if start <= moment_utc < start + timedelta(hours=1):
            # ForecastHour is an hourly energy bucket, therefore kWh over one
            # hour is also its average kW for this capacity calculation.
            return max(energy, 0.0)
    return None


def _current_proposal_solar_kw(self, config: SimulationConfig) -> float | None:
    """Return the same current proposal/live solar basis used by Alpha7.31."""
    try:
        evidence = alpha731._proposal_solar_evidence(self, config)
    except (AttributeError, TypeError, ValueError):
        return None
    if not isinstance(evidence, dict) or not evidence.get("available"):
        return None
    return _number(evidence.get("routed_solar_ac_kw"))


def _happy_hour_deadline_context(
    self,
    *,
    now: datetime,
    deadline: datetime,
    config: SimulationConfig,
) -> dict[str, Any]:
    """Return the remaining Happy Hour charge/discharge deadline obligation.

    Event priority deliberately blocks battery discharge during Happy Hour.  A
    future or active free charge also increases stored battery energy.  Both
    effects must therefore be represented when working backwards from the
    pre-cheap SOC target.
    """
    try:
        from . import agile_event_priority_runtime as events

        event = events._happy_hour_event(self)
    except (AttributeError, ImportError, TypeError, ValueError):
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


def _capacity_segments(
    self,
    *,
    now: datetime,
    deadline: datetime,
    config: SimulationConfig,
    blocked_start: datetime | None = None,
    blocked_end: datetime | None = None,
) -> list[dict[str, Any]]:
    """Build conservative solar-aware battery-output capacity to the deadline."""
    start = now.astimezone(UTC)
    finish = deadline.astimezone(UTC)
    if finish <= start:
        return []

    blocked_start = blocked_start.astimezone(UTC) if blocked_start is not None else None
    blocked_end = blocked_end.astimezone(UTC) if blocked_end is not None else None
    if blocked_start is not None:
        blocked_start = max(blocked_start, start)
    if blocked_end is not None:
        blocked_end = min(blocked_end, finish)
    if blocked_start is None or blocked_end is None or blocked_end <= blocked_start:
        blocked_start = None
        blocked_end = None

    effective_kw = _effective_deadline_kw(config)
    current_solar = _current_proposal_solar_kw(self, config)
    segments: list[dict[str, Any]] = []
    cursor = start
    first = True
    step = timedelta(minutes=CAPACITY_STEP_MINUTES)
    while cursor < finish:
        end = min(cursor + step, finish)
        # Split at Happy Hour boundaries so a partial five-minute segment is
        # never incorrectly counted as discharge-capable event time.
        for boundary in (blocked_start, blocked_end):
            if boundary is not None and cursor < boundary < end:
                end = boundary
        midpoint = cursor + (end - cursor) / 2
        forecast_solar = _forecast_solar_kw(self, midpoint)
        if first and current_solar is not None:
            solar_kw = current_solar
            basis = "current proposal/live solar"
        elif forecast_solar is not None:
            solar_kw = forecast_solar
            basis = "KEMS hourly solar forecast"
        elif current_solar is not None:
            # If the forecast has a hole, carrying the current solar level
            # forward is deliberately conservative for battery headroom.
            solar_kw = current_solar
            basis = "conservative current-solar fallback"
        else:
            solar_kw = 0.0
            basis = "no solar evidence"

        routed_solar = min(max(solar_kw, 0.0), max(config.inverter_limit_kw, 0.0))
        happy_hour_blocked = bool(
            blocked_start is not None
            and blocked_end is not None
            and blocked_start <= midpoint < blocked_end
        )
        battery_kw = (
            0.0
            if happy_hour_blocked
            else min(
                max(effective_kw, 0.0),
                max(config.inverter_limit_kw - routed_solar, 0.0),
                max(config.max_discharge_kw, 0.0),
            )
        )
        if happy_hour_blocked:
            basis = "Weekend Happy Hour event priority blocks battery discharge"
        hours = (end - cursor).total_seconds() / 3600.0
        segments.append(
            {
                "start": cursor,
                "end": end,
                "hours": hours,
                "solar_kw": routed_solar,
                "battery_kw": battery_kw,
                "capacity_kwh": battery_kw * hours,
                "basis": basis,
                "happy_hour_blocked": happy_hour_blocked,
            }
        )
        cursor = end
        first = False
    return segments


def _latest_safe_start(
    segments: list[dict[str, Any]],
    required_kwh: float,
) -> datetime | None:
    """Walk backwards and return the latest time full safe output can begin."""
    if required_kwh <= _EPSILON:
        return segments[-1]["end"] if segments else None

    remaining = required_kwh
    for segment in reversed(segments):
        capacity = max(float(segment.get("capacity_kwh") or 0.0), 0.0)
        battery_kw = max(float(segment.get("battery_kw") or 0.0), 0.0)
        if capacity + _EPSILON < remaining:
            remaining -= capacity
            continue
        if battery_kw <= _EPSILON:
            continue
        seconds = remaining / battery_kw * 3600.0
        return segment["end"] - timedelta(seconds=seconds)
    return None


def _deadline_guard_context(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Calculate latest-safe-start evidence for the current coordinator scan."""
    soc = rolling._current_agile_soc(state)
    target_soc = _target_percent(config)
    effective_kw = _effective_deadline_kw(config)
    deadline = agile._next_cheap(now, tariff).astimezone(UTC)
    now_utc = now.astimezone(UTC)
    capacity = max(config.battery_capacity_kwh, 0.1)
    efficiency = max(config.discharge_efficiency, 0.01)

    if soc is None or effective_kw <= _EPSILON or deadline <= now_utc:
        return {
            "available": False,
            "mode": "unavailable",
            "deadline": deadline.isoformat(),
            "target_soc_percent": round(target_soc, 1),
        }

    battery_kwh = capacity * min(max(soc, 0.0), 100.0) / 100.0
    target_kwh = capacity * target_soc / 100.0
    current_soc_required_ac = max(battery_kwh - target_kwh, 0.0) * efficiency
    happy_hour = _happy_hour_deadline_context(
        self,
        now=now,
        deadline=deadline,
        config=config,
    )
    happy_hour_obligation = max(
        _number(happy_hour.get("additional_discharge_obligation_kwh")) or 0.0,
        0.0,
    )
    happy_hour_stored_charge = max(
        _number(happy_hour.get("remaining_stored_charge_kwh")) or 0.0,
        0.0,
    )
    required_ac = current_soc_required_ac + happy_hour_obligation
    blocked_start = happy_hour.get("blocked_start")
    blocked_end = happy_hour.get("blocked_end")
    segments = _capacity_segments(
        self,
        now=now,
        deadline=deadline,
        config=config,
        blocked_start=blocked_start if isinstance(blocked_start, datetime) else None,
        blocked_end=blocked_end if isinstance(blocked_end, datetime) else None,
    )
    remaining_capacity = sum(float(item["capacity_kwh"]) for item in segments)
    margin = remaining_capacity - required_ac
    latest_safe = _latest_safe_start(segments, required_ac)
    guarded_start = (
        latest_safe - timedelta(minutes=DEADLINE_GUARD_MINUTES)
        if latest_safe is not None
        else now_utc
    )
    reachable = remaining_capacity + 0.05 >= required_ac

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
        float(segments[0]["battery_kw"]) if segments else effective_kw
    )
    skippable_half_hours = max(
        math.floor(max(margin, 0.0) / max(effective_kw * 0.5, 0.001)),
        0,
    )
    maximum_stored_discharge = remaining_capacity / efficiency
    projected_battery_kwh = min(battery_kwh + happy_hour_stored_charge, capacity)
    minimum_reachable_soc = max(
        (projected_battery_kwh - maximum_stored_discharge) / capacity * 100.0,
        target_soc if reachable else 0.0,
    )
    minimum_reachable_soc = min(max(minimum_reachable_soc, 0.0), 100.0)
    return {
        "available": True,
        "mode": mode,
        "generated_at": now.isoformat(),
        "deadline": deadline.isoformat(),
        "target_soc_percent": round(target_soc, 1),
        "simulated_soc_percent": round(soc, 2),
        "current_soc_required_discharge_kwh": round(current_soc_required_ac, 3),
        "required_discharge_kwh": round(required_ac, 3),
        "solar_aware_remaining_capacity_kwh": round(remaining_capacity, 3),
        "solar_aware_deadline_margin_kwh": round(margin, 3),
        "minimum_reachable_soc_percent": round(minimum_reachable_soc, 2),
        "target_physically_reachable_now": reachable,
        "latest_safe_export_start": latest_safe.isoformat() if latest_safe else None,
        "guarded_latest_safe_export_start": guarded_start.isoformat(),
        "deadline_guard_minutes": DEADLINE_GUARD_MINUTES,
        "deadline_guard_active": mode in {"deadline_following", "maximum_discharge"},
        "current_battery_headroom_kw": round(current_battery_headroom, 3),
        "required_average_discharge_kw": round(required_ac / hours, 3),
        "skippable_half_hours": skippable_half_hours,
        "capacity_model": (
            "5-minute solar-aware shared-inverter headroom; Happy Hour "
            "charge/discharge window protected"
            if happy_hour.get("active")
            else "5-minute solar-aware shared-inverter headroom"
        ),
        "forecast_solar_used": any(
            item.get("basis") == "KEMS hourly solar forecast" for item in segments
        ),
        "happy_hour_deadline_protected": bool(happy_hour.get("active")),
        "happy_hour_deadline_obligation_kwh": round(happy_hour_obligation, 3),
        "happy_hour_discharge_blocked_hours": round(
            max(_number(happy_hour.get("blocked_hours")) or 0.0, 0.0), 3
        ),
        "happy_hour_deadline_context": {
            key: value
            for key, value in happy_hour.items()
            if key not in {"blocked_start", "blocked_end"}
        },
    }


def install_alpha734_deadline_guard_patch() -> None:
    """Install latest-safe-start enforcement and diagnostics once."""
    update = runtime.EfficientAgileSmartExportManager.async_update
    if not getattr(update, "_kems_alpha734_deadline_guard", False):
        original_update = update

        async def update_with_alpha734(
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
            self._kems_alpha734_forecast = forecast
            return await original_update(
                self,
                records=records,
                now=now,
                config=config,
                learned=learned,
                forecast=forecast,
                forecast_plan=forecast_plan,
                tariff=tariff,
            )

        update_with_alpha734._kems_alpha734_deadline_guard = True
        runtime.EfficientAgileSmartExportManager.async_update = update_with_alpha734

    dispatch = alpha717._dispatch_targets
    if not getattr(dispatch, "_kems_alpha734_deadline_guard", False):
        original_dispatch = dispatch

        def dispatch_with_alpha734(
            self,
            state,
            plan,
            *,
            now,
            config,
            tariff,
        ):
            targets = original_dispatch(
                self,
                state,
                plan,
                now=now,
                config=config,
                tariff=tariff,
            )
            guard = _deadline_guard_context(
                self,
                state,
                now=now,
                config=config,
                tariff=tariff,
            )
            self._kems_alpha734_deadline_guard = guard
            targets["deadline_guard"] = guard
            if not guard.get("available"):
                return targets

            guard_mode = str(guard.get("mode") or "price_optimised")
            current_mode = str(targets.get("mode") or "price_optimised")
            if guard_mode == "target_reached":
                return targets
            if guard_mode not in {"deadline_following", "maximum_discharge"}:
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

            if guard_mode == "maximum_discharge":
                action = (
                    "maximum discharge — 10% target physically unreachable; "
                    "house first"
                )
            else:
                action = (
                    "deadline guard active — full safe discharge protects the "
                    "10% overnight target; house first"
                )
            targets.update(
                {
                    "mode": guard_mode,
                    "action": action,
                    "house_battery_kw": round(house_kw, 3),
                    "battery_export_target_kw": round(export_kw, 3),
                    "battery_discharge_target_kw": round(total_kw, 3),
                    "deadline_margin_kwh": guard.get("solar_aware_deadline_margin_kwh"),
                    "required_average_kw": guard.get("required_average_discharge_kw"),
                    "deadline_guard_escalated_from": current_mode,
                }
            )
            if evidence:
                evidence.update(
                    {
                        "deadline_guard_applied": True,
                        "permitted_battery_to_home_kw": round(house_kw, 3),
                        "permitted_battery_export_kw": round(export_kw, 3),
                        "permitted_total_discharge_kw": round(total_kw, 3),
                    }
                )
                targets["solar_aware_inverter_headroom"] = evidence
            return targets

        dispatch_with_alpha734._kems_alpha734_deadline_guard = True
        alpha717._dispatch_targets = dispatch_with_alpha734

    rolling_plan = rolling._rolling_plan
    if not getattr(rolling_plan, "_kems_alpha734_deadline_guard", False):
        original_plan = rolling_plan

        def rolling_plan_with_alpha734(
            self,
            state,
            *,
            now,
            config,
            tariff,
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
            guard = getattr(self, "_kems_alpha734_deadline_guard", None)
            if isinstance(guard, dict):
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
            return plan

        rolling_plan_with_alpha734._kems_alpha734_deadline_guard = True
        rolling._rolling_plan = rolling_plan_with_alpha734
