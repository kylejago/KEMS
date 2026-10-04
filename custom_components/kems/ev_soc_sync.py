"""Narrow, auditable EV state-of-charge sync into Ohme.

Alpha9.78 replaces an external Home Assistant automation with one explicitly
opt-in KEMS write path. The only permitted write is number.set_value on the
configured Ohme state-of-charge input.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from homeassistant.helpers.storage import Store

from .const import CONF_EV_SOC_SYNC_ENABLED, DOMAIN, STORAGE_NAMESPACE

_STORAGE_VERSION = 1
_TOLERANCE_PERCENT = 0.5
_WRITE_COOLDOWN_SECONDS = 30
_MAX_RECENT_EVENTS = 20
_CONNECTED_STATES = {"plugged_in", "plugged in", "charging"}


def _normalise(value: Any) -> str:
    return str(value or "").strip().casefold()


def _as_soc(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if 0.0 <= result <= 100.0 else None


def ev_soc_sync_write_decision(
    *,
    enabled: bool,
    emergency_stop: bool,
    connected: bool,
    source_soc: float | None,
    target_soc: float | None,
    cooldown_active: bool,
) -> tuple[bool, str, str]:
    """Return whether this scan may write the Ohme SOC input."""
    if not enabled:
        return False, "disabled", "EV SOC sync is disabled"
    if emergency_stop:
        return False, "blocked", "KEMS emergency stop is active"
    if not connected:
        return False, "idle", "EV is not connected"
    if source_soc is None:
        return False, "waiting_source", "Vehicle SOC source is unavailable or invalid"
    if target_soc is None:
        return False, "waiting_target", "Ohme SOC input is unavailable or invalid"
    if abs(source_soc - target_soc) < _TOLERANCE_PERCENT:
        return False, "matched", "Vehicle and Ohme SOC already match"
    if cooldown_active:
        return False, "cooldown", "Previous SOC write is still inside the cooldown"
    return True, "write", "Vehicle and Ohme SOC differ"


class EVSOCSyncController:
    """Own only the explicitly enabled Ohme SOC-input write."""

    def __init__(
        self,
        hass: Any,
        entry: Any,
        *,
        vehicle_soc_entity: str | None,
        ohme_soc_input_entity: str | None,
        ev_status_entity: str | None,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._vehicle_soc_entity = vehicle_soc_entity
        self._ohme_soc_input_entity = ohme_soc_input_entity
        self._ev_status_entity = ev_status_entity
        self._store = Store(
            hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}.{STORAGE_NAMESPACE}.ev_soc_sync",
        )
        self._attempt_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._last_attempt_at: str | None = None
        self._last_success_at: str | None = None
        self._last_result = "Never evaluated"
        self._last_status = "unknown"
        self._events: list[dict[str, Any]] = []
        self._status: dict[str, Any] = {}

    @property
    def status(self) -> dict[str, Any]:
        """Return the current diagnostic status."""
        return dict(self._status)

    async def async_setup(self) -> None:
        """Restore compact audit counters and recent events."""
        data = await self._store.async_load()
        if not isinstance(data, dict):
            return
        self._attempt_count = int(data.get("attempt_count") or 0)
        self._success_count = int(data.get("success_count") or 0)
        self._failure_count = int(data.get("failure_count") or 0)
        self._last_attempt_at = data.get("last_attempt_at")
        self._last_success_at = data.get("last_success_at")
        self._last_result = str(data.get("last_result") or self._last_result)
        events = data.get("recent_events")
        if isinstance(events, list):
            self._events = [
                dict(item)
                for item in events[-_MAX_RECENT_EVENTS:]
                if isinstance(item, dict)
            ]

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "attempt_count": self._attempt_count,
                "success_count": self._success_count,
                "failure_count": self._failure_count,
                "last_attempt_at": self._last_attempt_at,
                "last_success_at": self._last_success_at,
                "last_result": self._last_result,
                "recent_events": list(self._events[-_MAX_RECENT_EVENTS:]),
            }
        )

    def _state_value(self, entity_id: str | None) -> Any:
        state = self._hass.states.get(entity_id) if entity_id else None
        return state.state if state is not None else None

    def _connected(self, snapshot: Any) -> bool:
        if getattr(snapshot, "ev_connected", None) is True:
            return True
        return (
            _normalise(self._state_value(self._ev_status_entity)) in _CONNECTED_STATES
        )

    def _cooldown_active(self, now: datetime) -> bool:
        if not self._last_attempt_at:
            return False
        try:
            previous = datetime.fromisoformat(self._last_attempt_at)
        except ValueError:
            return False
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=UTC)
        return (
            now - previous.astimezone(UTC)
        ).total_seconds() < _WRITE_COOLDOWN_SECONDS

    def _record_event(self, payload: dict[str, Any]) -> None:
        self._events.append(dict(payload))
        self._events = self._events[-_MAX_RECENT_EVENTS:]

    def _publish(
        self,
        *,
        enabled: bool,
        connected: bool,
        source_soc: float | None,
        target_soc: float | None,
        status: str,
        reason: str,
        trigger: dict[str, Any] | None,
        readback_soc: float | None = None,
    ) -> None:
        self._last_status = status
        self._status = {
            "enabled": enabled,
            "vehicle_soc_entity": self._vehicle_soc_entity,
            "ohme_soc_input_entity": self._ohme_soc_input_entity,
            "ev_status_entity": self._ev_status_entity,
            "connected": connected,
            "vehicle_soc_percent": source_soc,
            "ohme_soc_input_percent": target_soc,
            "readback_soc_percent": readback_soc,
            "status": status,
            "reason": reason,
            "last_result": self._last_result,
            "last_trigger": dict(trigger) if isinstance(trigger, dict) else None,
            "attempt_count": self._attempt_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "last_attempt_at": self._last_attempt_at,
            "last_success_at": self._last_success_at,
            "write_tolerance_percent": _TOLERANCE_PERCENT,
            "write_cooldown_seconds": _WRITE_COOLDOWN_SECONDS,
            "recent_events": list(self._events),
            "write_scope": "Ohme SOC input only; no charge-mode or FoxESS authority",
        }

    async def async_update(
        self,
        *,
        snapshot: Any,
        emergency_stop: bool,
        trigger: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate and optionally synchronise the Ohme SOC input."""
        enabled = bool(self._entry.options.get(CONF_EV_SOC_SYNC_ENABLED, False))
        source_soc = _as_soc(self._state_value(self._vehicle_soc_entity))
        target_soc = _as_soc(self._state_value(self._ohme_soc_input_entity))
        connected = self._connected(snapshot)
        now = datetime.now(UTC)
        allow, status, reason = ev_soc_sync_write_decision(
            enabled=enabled,
            emergency_stop=emergency_stop,
            connected=connected,
            source_soc=source_soc,
            target_soc=target_soc,
            cooldown_active=self._cooldown_active(now),
        )

        if not allow:
            if trigger is not None or status != self._last_status:
                self._record_event(
                    {
                        "timestamp": now.isoformat(),
                        "status": status,
                        "reason": reason,
                        "vehicle_soc_percent": source_soc,
                        "ohme_soc_input_percent": target_soc,
                        "trigger": dict(trigger) if isinstance(trigger, dict) else None,
                    }
                )
                await self._async_save()
            self._last_result = reason
            self._publish(
                enabled=enabled,
                connected=connected,
                source_soc=source_soc,
                target_soc=target_soc,
                status=status,
                reason=reason,
                trigger=trigger,
            )
            return self.status

        self._attempt_count += 1
        self._last_attempt_at = now.isoformat()
        requested = round(float(source_soc), 1)

        try:
            async with asyncio.timeout(15):
                await self._hass.services.async_call(
                    "number",
                    "set_value",
                    {
                        "entity_id": self._ohme_soc_input_entity,
                        "value": requested,
                    },
                    blocking=True,
                )
            await asyncio.sleep(2)
            readback_soc = _as_soc(self._state_value(self._ohme_soc_input_entity))
            confirmed = (
                readback_soc is not None
                and abs(readback_soc - requested) < _TOLERANCE_PERCENT
            )
            if confirmed:
                status = "success"
                reason = f"Ohme SOC input confirmed at {readback_soc:.1f}%"
                self._success_count += 1
                self._last_success_at = datetime.now(UTC).isoformat()
            else:
                status = "readback_pending"
                reason = (
                    f"Requested {requested:.1f}% but immediate readback is "
                    f"{readback_soc if readback_soc is not None else 'unavailable'}"
                )
            self._last_result = reason
        except Exception as err:
            readback_soc = _as_soc(self._state_value(self._ohme_soc_input_entity))
            status = "failed"
            reason = f"Ohme SOC write failed: {err}"
            self._last_result = reason
            self._failure_count += 1

        self._record_event(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "status": status,
                "reason": reason,
                "vehicle_soc_percent": source_soc,
                "previous_ohme_soc_input_percent": target_soc,
                "requested_ohme_soc_percent": requested,
                "readback_soc_percent": readback_soc,
                "trigger": dict(trigger) if isinstance(trigger, dict) else None,
            }
        )
        await self._async_save()
        self._publish(
            enabled=enabled,
            connected=connected,
            source_soc=source_soc,
            target_soc=target_soc,
            status=status,
            reason=reason,
            trigger=trigger,
            readback_soc=readback_soc,
        )
        return self.status

    async def async_shutdown(self) -> None:
        """Flush the compact diagnostic audit on unload."""
        await self._async_save()
