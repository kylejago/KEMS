"""Alpha 7.22 Agile price-horizon readiness and battery-export safety."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from . import agile_rolling_replan as rolling
from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from .agile_price_horizon import missing_slots_for_day, remaining_price_horizon
from .tariff import TariffSettings

_HORIZON_SENSOR = "sensor.kems_agile_price_horizon_status"
_STATUS_SENSOR = "sensor.kems_agile_smart_export_status"
_DEADLINE_OVERRIDE_MODES = frozenset({"deadline_following", "maximum_discharge"})


def _planning_horizon(
    state: dict[str, Any],
    *,
    now: datetime,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Describe known Agile prices from now until the next normal cheap period."""
    local_now = now.astimezone(agile.LONDON)
    deadline = agile._next_cheap(now, tariff)
    if agile._in_window(
        local_now.time(),
        tariff.offpeak_start,
        tariff.offpeak_end,
    ):
        return {
            "complete": True,
            "status": "cheap_period_active",
            "expected_count": 0,
            "known_count": 0,
            "missing_count": 0,
            "missing_slots": [],
            "missing_labels": [],
            "current_slot_known": True,
            "deadline": deadline.isoformat(),
            "battery_export_held": False,
            "deadline_override": False,
        }

    slots = state.get("today_slots")
    slots = slots if isinstance(slots, list) else []
    horizon = remaining_price_horizon(
        slots,
        now=now,
        deadline=deadline,
        timezone=agile.LONDON,
    )
    missing = horizon.get("missing_slots", [])
    horizon.update(
        {
            "status": "complete" if horizon["complete"] else "incomplete",
            "missing_labels": [
                str(item.get("label") or item.get("local_from") or "unknown")
                for item in missing
                if isinstance(item, dict)
            ],
            "deadline": deadline.isoformat(),
            "battery_export_held": False,
            "deadline_override": False,
        }
    )
    return horizon


def _annotate_price_quality(state: dict[str, Any], now: datetime) -> None:
    """Add exact missing-slot diagnostics without changing settlement readiness."""
    quality = state.get("price_quality")
    if not isinstance(quality, dict):
        return

    local = now.astimezone(agile.LONDON)
    today_slots = state.get("today_slots")
    today_slots = today_slots if isinstance(today_slots, list) else []
    tomorrow_slots = state.get("tomorrow_slots")
    tomorrow_slots = tomorrow_slots if isinstance(tomorrow_slots, list) else []

    today_missing = missing_slots_for_day(today_slots, local.date(), agile.LONDON)
    tomorrow_missing = missing_slots_for_day(
        tomorrow_slots,
        local.date() + timedelta(days=1),
        agile.LONDON,
    )
    quality["today_missing_count"] = len(today_missing)
    quality["today_missing_slots"] = today_missing
    quality["today_missing_labels"] = [
        str(item.get("label") or item.get("local_from") or "unknown")
        for item in today_missing
    ]
    quality["tomorrow_missing_count"] = len(tomorrow_missing)
    quality["tomorrow_missing_slots"] = tomorrow_missing
    quality["tomorrow_missing_labels"] = [
        str(item.get("label") or item.get("local_from") or "unknown")
        for item in tomorrow_missing
    ]


def _hold_price_optimised_export(
    state: dict[str, Any],
    plan: dict[str, Any],
    horizon: dict[str, Any],
    *,
    now: datetime,
) -> None:
    """Suppress deliberate battery export while relevant future prices are unknown."""
    mode = str(plan.get("dispatch_mode") or "price_optimised")
    current_known = bool(horizon.get("current_slot_known"))
    deadline_override = mode in _DEADLINE_OVERRIDE_MODES and current_known
    horizon["deadline_override"] = deadline_override

    if horizon.get("complete") or deadline_override:
        if deadline_override and not horizon.get("complete"):
            horizon["status"] = "deadline_override"
        return

    horizon["battery_export_held"] = True
    horizon["status"] = "holding_battery_export"
    missing_labels = ", ".join(horizon.get("missing_labels") or []) or "future slot"
    action = f"hold battery export — waiting for Agile price horizon ({missing_labels})"
    state["current_action"] = action

    house_kw = float(plan.get("current_house_battery_kw") or 0.0)
    plan["dispatch_mode"] = "price_horizon_hold"
    plan["dispatch_action"] = action
    plan["current_battery_export_target_kw"] = 0.0
    plan["current_battery_discharge_target_kw"] = round(max(house_kw, 0.0), 3)
    plan["selected_slots"] = []
    plan["planned_battery_export_kwh"] = 0.0
    plan["next_export_slot"] = None
    plan["required_in_current_slot_kwh"] = 0.0
    plan["unallocated_exportable_kwh"] = round(
        float(plan.get("exportable_battery_energy_kwh") or 0.0),
        3,
    )

    now_utc = now.astimezone(UTC)
    deadline_text = horizon.get("deadline")
    try:
        deadline = datetime.fromisoformat(str(deadline_text)).astimezone(UTC)
    except (TypeError, ValueError):
        deadline = None
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        try:
            start = datetime.fromisoformat(str(slot["valid_from"])).astimezone(UTC)
            end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
        except (KeyError, TypeError, ValueError):
            continue
        if end <= now_utc or (deadline is not None and start >= deadline):
            continue
        slot["rolling_planned_battery_export_kwh"] = 0.0
        slot["rolling_target_battery_export_kw"] = 0.0
        slot["rolling_action"] = action
        slot["actions"] = [action]


def install_alpha722_price_horizon_patch() -> None:
    """Install provisional readiness plus incomplete-horizon export protection."""
    original_rolling_plan = rolling._rolling_plan
    if not getattr(original_rolling_plan, "_kems_alpha722_horizon", False):

        def rolling_plan_with_horizon(
            self,
            state,
            *,
            now,
            config,
            tariff,
        ):
            plan = original_rolling_plan(
                self,
                state,
                now=now,
                config=config,
                tariff=tariff,
            )
            horizon = _planning_horizon(state, now=now, tariff=tariff)
            _hold_price_optimised_export(
                state,
                plan,
                horizon,
                now=now,
            )
            plan["price_horizon_complete"] = bool(horizon.get("complete"))
            plan["price_horizon_status"] = horizon.get("status")
            plan["price_horizon_expected_slots"] = horizon.get("expected_count")
            plan["price_horizon_known_slots"] = horizon.get("known_count")
            plan["price_horizon_missing_slots"] = horizon.get("missing_count")
            plan["price_horizon_missing_labels"] = horizon.get("missing_labels")
            plan["price_horizon_battery_export_held"] = bool(
                horizon.get("battery_export_held")
            )
            plan["price_horizon_deadline_override"] = bool(
                horizon.get("deadline_override")
            )
            state["planning_horizon"] = dict(horizon)
            return plan

        rolling_plan_with_horizon._kems_alpha722_horizon = True
        rolling._rolling_plan = rolling_plan_with_horizon

    original_publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(original_publish, "_kems_alpha722_horizon", False):

        def publish_with_horizon(self, state: dict[str, Any]) -> None:
            now = getattr(self, "_rolling_now", None)
            if not isinstance(now, datetime):
                try:
                    now = datetime.fromisoformat(str(state.get("generated_at")))
                except (TypeError, ValueError):
                    now = None
            if isinstance(now, datetime):
                _annotate_price_quality(state, now)

            original_publish(self, state)

            horizon = state.get("planning_horizon")
            horizon = horizon if isinstance(horizon, dict) else {}
            periods = state.get("periods")
            periods = periods if isinstance(periods, dict) else {}
            today = periods.get("today")
            today = today if isinstance(today, dict) else {}
            live_ready = bool(
                today.get("ready")
                and horizon.get("current_slot_known")
                and state.get("current_rate_pence") is not None
            )
            settlement_ready = bool(state.get("ready"))
            state["live_ready"] = live_ready
            state["settlement_ready"] = settlement_ready

            if settlement_ready:
                status = "Ready"
            elif live_ready and horizon.get("complete"):
                status = "Ready — live horizon complete"
            elif live_ready:
                status = "Ready — provisional price horizon"
            elif horizon and not horizon.get("current_slot_known"):
                status = "Waiting for current Agile price"
            else:
                status = "Waiting for simulation coverage"

            existing = self._hass.states.get(_STATUS_SENSOR)
            attrs = dict(existing.attributes) if existing is not None else {}
            attrs.update(
                {
                    "live_ready": live_ready,
                    "settlement_ready": settlement_ready,
                    "planning_horizon_complete": horizon.get("complete"),
                    "planning_horizon_status": horizon.get("status"),
                    "planning_horizon_deadline": horizon.get("deadline"),
                    "planning_horizon_missing_count": horizon.get("missing_count"),
                    "planning_horizon_missing_labels": horizon.get("missing_labels"),
                    "battery_export_held_for_price_horizon": horizon.get(
                        "battery_export_held"
                    ),
                    "deadline_override_active": horizon.get("deadline_override"),
                    "current_action": state.get("current_action"),
                }
            )
            self._set(_STATUS_SENSOR, status, attrs)

            if horizon:
                if horizon.get("deadline_override"):
                    horizon_state = "Deadline override"
                elif horizon.get("battery_export_held"):
                    horizon_state = "Holding battery export"
                elif horizon.get("complete"):
                    horizon_state = "Complete"
                else:
                    horizon_state = "Incomplete"
                self._set(
                    _HORIZON_SENSOR,
                    horizon_state,
                    {
                        "friendly_name": "Agile battery-export price horizon",
                        "mode": "simulation_only",
                        **horizon,
                    },
                )

        publish_with_horizon._kems_alpha722_horizon = True
        runtime.EfficientAgileSmartExportManager._publish = publish_with_horizon
