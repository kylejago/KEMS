"""Persistent validation and audit trail for KEMS shadow control.

This module records what KEMS would ask the inverter to do and compares that
request with the digital twin. It deliberately never calls a hardware service.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .kems_core import ControlConfig, ControlState, SimulationState, Snapshot
from .kems_core.shadow_validation import (
    shadow_plan_vs_outcome,
    validate_shadow_command,
)

STORE_VERSION = 1
SAVE_INTERVAL = timedelta(minutes=5)
MAX_SETTLED_SLOTS = 14 * 48
MAX_DECISIONS = 250

_ENTITY_IDS = (
    "sensor.kems_shadow_control_status",
    "sensor.kems_shadow_control_readiness",
    "sensor.kems_shadow_command_safety",
    "sensor.kems_shadow_tracking_score",
    "sensor.kems_shadow_plan_vs_outcome",
    "sensor.kems_shadow_decision_audit",
    "sensor.kems_shadow_half_hour_validation",
)

_TRACKED_FIELDS = (
    "charge_kw",
    "battery_to_home_kw",
    "battery_export_kw",
    "total_discharge_kw",
)


def _slot_key(now: datetime) -> str:
    """Return the local half-hour bucket containing now."""
    return now.replace(
        minute=(now.minute // 30) * 30,
        second=0,
        microsecond=0,
    ).isoformat()


def _round_or_none(value: Any, digits: int = 3) -> float | None:
    """Return one rounded float if it is numeric."""
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


class ShadowValidationRecorder:
    """Audit desired commands and their digital-twin outcome without writes."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORE_VERSION,
            f"{DOMAIN}.{entry_id}.shadow_validation",
        )
        self._settled: list[dict[str, Any]] = []
        self._decisions: list[dict[str, Any]] = []
        self._active: dict[str, Any] | None = None
        self._last_signature: tuple[Any, ...] | None = None
        self._last_save: datetime | None = None
        self._dirty = False
        self._state: dict[str, Any] = {}

    @property
    def state(self) -> dict[str, Any]:
        """Return the current shadow-validation state."""
        return dict(self._state)

    async def async_load(self) -> None:
        """Restore settled half-hours and decision evidence."""
        data = await self._store.async_load() or {}
        settled = data.get("settled_half_hours", [])
        decisions = data.get("decisions", [])
        self._settled = (
            [dict(item) for item in settled if isinstance(item, dict)][
                -MAX_SETTLED_SLOTS:
            ]
            if isinstance(settled, list)
            else []
        )
        self._decisions = (
            [dict(item) for item in decisions if isinstance(item, dict)][
                -MAX_DECISIONS:
            ]
            if isinstance(decisions, list)
            else []
        )

    async def async_update(
        self,
        *,
        snapshot: Snapshot,
        simulation: SimulationState,
        control: ControlState,
        now: datetime,
        config: ControlConfig,
        agile_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate and retain one coordinator-scan shadow decision."""
        safety = validate_shadow_command(control, config)
        tracking = shadow_plan_vs_outcome(control, simulation)
        self._update_half_hour(now, control, safety, tracking, agile_state)
        self._record_decision(now, control, safety, tracking, agile_state)

        ready = bool(
            safety.get("passed")
            and control.data_fresh
            and control.plan_safe
            and control.preflight_status == "PASS"
            and simulation.ready
            and not config.emergency_stop
        )
        if config.emergency_stop:
            status = "Emergency stop"
        elif not safety.get("passed"):
            status = "Blocked — shadow safety validation"
        elif control.operating_mode == "shadow":
            status = "Shadow active"
        elif control.operating_mode == "control":
            status = "Live control blocked — no real backend"
        elif control.operating_mode == "simulate":
            status = "Ready for shadow" if ready else "Simulation validation"
        else:
            status = "Observe only"

        current_agile = agile_state.get("current_action")
        dispatch_mode = self._state_value(
            "sensor.kems_agile_dispatch_mode",
            default="unavailable",
        )
        raw_hardware_battery = _round_or_none(snapshot.battery_power_kw)
        hardware_available = raw_hardware_battery is not None
        self._state = {
            "status": status,
            "ready_for_shadow": ready,
            "operating_mode": control.operating_mode,
            "command_safety": safety,
            "tracking": tracking,
            "operating_reason": control.operating_reason,
            "desired_work_mode": control.desired_work_mode,
            "next_action": control.next_action,
            "blocked_reason": control.blocked_reason,
            "agile_action": current_agile,
            "agile_dispatch_mode": dispatch_mode,
            "actual_hardware_available": hardware_available,
            "raw_hardware_battery_power_kw": raw_hardware_battery,
            "comparison_basis": "digital_twin",
            "hardware_comparison_note": (
                "Physical battery direction comparison is deferred until FoxESS "
                "commissioning verifies sign conventions"
            ),
            "settled_half_hours": len(self._settled),
            "recent_half_hours": self._settled[-12:],
            "recent_decisions": self._decisions[-20:],
            "generated_at": now.isoformat(),
            "real_backend_available": False,
            "hardware_writes": "blocked",
        }
        self._publish()
        await self._save_if_due(now)
        return self.state

    def _update_half_hour(
        self,
        now: datetime,
        control: ControlState,
        safety: dict[str, Any],
        tracking: dict[str, Any],
        agile_state: dict[str, Any],
    ) -> None:
        """Build one averaged validation result for every completed half-hour."""
        key = _slot_key(now)
        if self._active is not None and self._active.get("slot") != key:
            settled = self._finalise_active(self._active)
            if settled is not None:
                self._settled.append(settled)
                self._settled = self._settled[-MAX_SETTLED_SLOTS:]
                self._dirty = True
            self._active = None

        if self._active is None:
            self._active = {
                "slot": key,
                "samples": 0,
                "target_sums": {name: 0.0 for name in _TRACKED_FIELDS},
                "target_counts": {name: 0 for name in _TRACKED_FIELDS},
                "outcome_sums": {name: 0.0 for name in _TRACKED_FIELDS},
                "outcome_counts": {name: 0 for name in _TRACKED_FIELDS},
                "safety_passed_all": True,
                "reasons": [],
                "agile_actions": [],
            }

        active = self._active
        active["samples"] += 1
        target = tracking.get("target", {})
        outcome = tracking.get("outcome", {})
        for name in _TRACKED_FIELDS:
            target_value = _round_or_none(target.get(name))
            if target_value is not None:
                active["target_sums"][name] += target_value
                active["target_counts"][name] += 1
            outcome_value = _round_or_none(outcome.get(name))
            if outcome_value is not None:
                active["outcome_sums"][name] += outcome_value
                active["outcome_counts"][name] += 1
        active["safety_passed_all"] = bool(
            active["safety_passed_all"] and safety.get("passed")
        )
        reason = str(control.operating_reason)
        if reason not in active["reasons"]:
            active["reasons"].append(reason)
        agile_action = agile_state.get("current_action")
        if agile_action and str(agile_action) not in active["agile_actions"]:
            active["agile_actions"].append(str(agile_action))

    @staticmethod
    def _finalise_active(active: dict[str, Any]) -> dict[str, Any] | None:
        """Convert a half-hour accumulator into compact evidence."""
        if int(active.get("samples") or 0) <= 0:
            return None
        target: dict[str, float | None] = {}
        outcome: dict[str, float | None] = {}
        difference: dict[str, float | None] = {}
        within: dict[str, bool | None] = {}
        for name in _TRACKED_FIELDS:
            target_count = int(active["target_counts"].get(name) or 0)
            outcome_count = int(active["outcome_counts"].get(name) or 0)
            target[name] = (
                round(active["target_sums"][name] / target_count, 3)
                if target_count
                else None
            )
            outcome[name] = (
                round(active["outcome_sums"][name] / outcome_count, 3)
                if outcome_count
                else None
            )
            if target[name] is None or outcome[name] is None:
                difference[name] = None
                within[name] = None
            else:
                delta = float(outcome[name]) - float(target[name])
                difference[name] = round(delta, 3)
                within[name] = abs(delta) <= 0.35
        scored = [value for value in within.values() if value is not None]
        score = (
            round(100 * sum(1 for value in scored if value) / len(scored), 1)
            if scored
            else None
        )
        return {
            "slot": active.get("slot"),
            "samples": int(active.get("samples") or 0),
            "basis": "digital_twin",
            "target": target,
            "outcome": outcome,
            "difference": difference,
            "tracking_score_percent": score,
            "safety_passed_all": bool(active.get("safety_passed_all")),
            "operating_reasons": list(active.get("reasons", [])),
            "agile_actions": list(active.get("agile_actions", [])),
        }

    def _record_decision(
        self,
        now: datetime,
        control: ControlState,
        safety: dict[str, Any],
        tracking: dict[str, Any],
        agile_state: dict[str, Any],
    ) -> None:
        """Retain command changes rather than writing a duplicate every scan."""
        target = tracking.get("target", {})
        signature = (
            control.operating_reason,
            control.desired_work_mode,
            *(target.get(name) for name in _TRACKED_FIELDS),
            agile_state.get("current_action"),
        )
        if signature == self._last_signature:
            return
        self._last_signature = signature
        self._decisions.append(
            {
                "timestamp": now.isoformat(),
                "operating_reason": control.operating_reason,
                "desired_work_mode": control.desired_work_mode,
                "target": dict(target),
                "tracking_score_percent": tracking.get("tracking_score_percent"),
                "safety_passed": bool(safety.get("passed")),
                "agile_action": agile_state.get("current_action"),
                "next_action": control.next_action,
            }
        )
        self._decisions = self._decisions[-MAX_DECISIONS:]
        self._dirty = True

    def _publish(self) -> None:
        """Publish compact first-class entities for the consolidated dashboard."""
        safety = self._state.get("command_safety", {})
        tracking = self._state.get("tracking", {})
        common = {
            "mode": "simulation_shadow_only",
            "hardware_writes": "blocked",
            "generated_at": self._state.get("generated_at"),
        }
        self._set(
            "sensor.kems_shadow_control_status",
            self._state.get("status", "Unavailable"),
            {
                "friendly_name": "KEMS shadow control status",
                "operating_mode": self._state.get("operating_mode"),
                "operating_reason": self._state.get("operating_reason"),
                "desired_work_mode": self._state.get("desired_work_mode"),
                "next_action": self._state.get("next_action"),
                "blocked_reason": self._state.get("blocked_reason"),
                **common,
            },
        )
        self._set(
            "sensor.kems_shadow_control_readiness",
            "Ready" if self._state.get("ready_for_shadow") else "Not ready",
            {
                "friendly_name": "KEMS shadow control readiness",
                "actual_hardware_available": self._state.get(
                    "actual_hardware_available"
                ),
                "comparison_basis": self._state.get("comparison_basis"),
                "hardware_comparison_note": self._state.get("hardware_comparison_note"),
                **common,
            },
        )
        self._set(
            "sensor.kems_shadow_command_safety",
            "PASS" if safety.get("passed") else "FAIL",
            {
                "friendly_name": "KEMS independent shadow command safety",
                **dict(safety),
                **common,
            },
        )
        self._set(
            "sensor.kems_shadow_tracking_score",
            tracking.get("tracking_score_percent", "Unavailable"),
            {
                "friendly_name": "KEMS shadow plan tracking score",
                "unit_of_measurement": "%",
                "comparison_basis": "digital_twin",
                "tolerance_kw": tracking.get("tolerance_kw"),
                **common,
            },
        )
        self._set(
            "sensor.kems_shadow_plan_vs_outcome",
            "Ready" if tracking.get("available") else "Collecting",
            {
                "friendly_name": "KEMS shadow plan vs digital-twin outcome",
                **dict(tracking),
                **common,
            },
        )
        self._set(
            "sensor.kems_shadow_decision_audit",
            f"{len(self._decisions)} decisions",
            {
                "friendly_name": "KEMS shadow decision audit",
                "recent_decisions": self._decisions[-20:],
                "agile_action": self._state.get("agile_action"),
                "agile_dispatch_mode": self._state.get("agile_dispatch_mode"),
                **common,
            },
        )
        self._set(
            "sensor.kems_shadow_half_hour_validation",
            f"{len(self._settled)} settled slots",
            {
                "friendly_name": "KEMS settled half-hour plan validation",
                "recent_half_hours": self._settled[-12:],
                "retained_half_hours": len(self._settled),
                **common,
            },
        )

    def _state_value(self, entity_id: str, *, default: str) -> str:
        state = self._hass.states.get(entity_id)
        return str(state.state) if state is not None else default

    def _set(self, entity_id: str, value: Any, attributes: dict[str, Any]) -> None:
        self._hass.states.async_set(entity_id, str(value), attributes)

    async def _save_if_due(self, now: datetime) -> None:
        if not self._dirty:
            return
        if self._last_save is not None and now - self._last_save < SAVE_INTERVAL:
            return
        await self.async_save()
        self._last_save = now

    async def async_save(self) -> None:
        """Persist compact evidence without writing every coordinator scan."""
        if not self._dirty:
            return
        await self._store.async_save(
            {
                "settled_half_hours": self._settled[-MAX_SETTLED_SLOTS:],
                "decisions": self._decisions[-MAX_DECISIONS:],
            }
        )
        self._dirty = False

    async def async_shutdown(self) -> None:
        """Flush evidence and remove transient state entities."""
        await self.async_save()
        for entity_id in _ENTITY_IDS:
            self._hass.states.async_remove(entity_id)
