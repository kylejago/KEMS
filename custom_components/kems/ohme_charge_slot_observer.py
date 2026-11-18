"""Optional read-only observer of native Ohme planned charging sessions.

Observations never enter KEMS Snapshot, commissioning, tariff resolving or
FoxESS control. The official service only lists charger plans; the supplier
has not independently confirmed discounted house-electricity hours.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .kems_core.ohme_charge_slot_plan import observe_ohme_slot_response
from .legacy_intelligent_parity_monitor import LegacyIntelligentParityMonitor
from .providers.entity_map import KEMSEntities

POLL_INTERVAL_SECONDS = 90
PLAN_FRESH_SECONDS = 180


class OhmeChargeSlotObserver:
    """Read-only, best-effort independent of critical control refresh cadence."""

    def __init__(self, hass: HomeAssistant, entities: KEMSEntities) -> None:
        self._hass = hass
        self._entities = entities
        self._unsubscribe: Any = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._last_attempt: datetime | None = None
        self._last_success: datetime | None = None
        self._last_result: dict[str, Any] = {}
        self._last_error: str | None = None
        self._last_state: str = "not_yet_polled"
        self._config_entry_id: str | None = None
        self._sensor_entity_id: str | None = None
        self._legacy_parity = LegacyIntelligentParityMonitor(hass, entities)
        self._legacy_parity_error: str | None = None

    def _resolve_ohme_sources(self) -> str | None:
        """Select only the Ohme account owning the configured EV status."""
        registry = er.async_get(self._hass)
        existing = registry.async_get(self._entities.ev_status or "")
        if existing is None or existing.platform != "ohme":
            self._last_state = "ohme_status_not_mapped"
            return None
        entry_id = existing.config_entry_id
        available = {
            entry.entry_id for entry in self._hass.config_entries.async_entries("ohme")
        }
        if not entry_id or entry_id not in available:
            self._last_state = "ohme_account_not_available"
            return None
        self._config_entry_id = entry_id
        candidate_ids = sorted(
            registered.entity_id
            for registered in registry.entities.values()
            if registered.config_entry_id == entry_id
            and registered.platform == "ohme"
            and registered.entity_id.startswith("sensor.")
            and registered.entity_id.endswith("_charge_slots")
        )
        self._sensor_entity_id = candidate_ids[0] if candidate_ids else None
        return entry_id

    @property
    def status(self) -> dict[str, Any]:
        """Diagnostics only; never consumed by control/commissioning."""
        now = dt_util.now()
        age = (
            max((now - self._last_success).total_seconds(), 0)
            if self._last_success is not None
            else None
        )
        sensor_state = (
            self._hass.states.get(self._sensor_entity_id)
            if self._sensor_entity_id
            else None
        )
        source_state = sensor_state.state if sensor_state is not None else None
        usable = age is not None and age <= PLAN_FRESH_SECONDS
        return {
            "read_only": True,
            "legacy_intelligent_comparison": self._legacy_parity.status,
            "legacy_comparison_error_type": self._legacy_parity_error,
            "uses_service": "ohme.list_charge_slots",
            "poll_seconds": POLL_INTERVAL_SECONDS,
            "last_state": self._last_state,
            "last_attempt": (
                self._last_attempt.isoformat() if self._last_attempt else None
            ),
            "last_success": (
                self._last_success.isoformat() if self._last_success else None
            ),
            "last_success_age_seconds": round(age, 1) if age is not None else None,
            "recent_observation": usable,
            "last_error_type": self._last_error,
            "slot_sensor": self._sensor_entity_id,
            "slot_sensor_state": (
                source_state[:256] if source_state is not None else None
            ),
            "slot_sensor_unknown_is_not_a_fault": source_state
            in {"unknown", "unavailable"},
            "last_plan": self._last_result if usable else {},
            "unverified_ohme_extra_discount": True,
            "supplier_discount_confirmed": False,
            "controls_foxess_or_ohme": False,
            "used_in_commissioning": False,
            "used_in_tariff_resolution": False,
            "import_or_export_authority": False,
        }

    async def async_setup(self) -> None:
        """Schedule independent reads; never hold up first KEMS control scan."""
        self._unsubscribe = async_track_time_interval(
            self._hass, self._schedule_poll, timedelta(seconds=POLL_INTERVAL_SECONDS)
        )
        self._schedule_poll(dt_util.now())

    @callback
    def _schedule_poll(self, _now: datetime) -> None:
        if self._closed:
            return
        plan_age = (
            max((_now - self._last_success).total_seconds(), 0)
            if self._last_success is not None
            else None
        )
        plan_active: bool | None = None
        if (
            plan_age is not None
            and plan_age <= PLAN_FRESH_SECONDS
            and self._last_result.get("status")
            in {"plan_observed", "no_slots_reported"}
        ):
            plan_active = bool(self._last_result.get("active_count", 0))
        try:
            self._legacy_parity.observe(now=_now, ohme_plan_active=plan_active)
            self._legacy_parity_error = None
        except Exception as error:
            # A comparison is optional diagnostics; it must not stop Ohme
            # observation, tariff refresh, or the physical KEMS controller.
            self._legacy_parity_error = type(error).__name__
        if self._task is not None and not self._task.done():
            return
        self._task = self._hass.async_create_task(self._async_poll())

    async def _async_poll(self) -> None:
        """Fetch canonical slot timestamps only while the vehicle is connected."""
        try:
            entry_id = self._resolve_ohme_sources()
            if not entry_id:
                return
            source = self._hass.states.get(self._entities.ev_status)
            state = source.state.casefold() if source is not None else ""
            if state in {"", "unavailable", "unknown", "unplugged", "none"}:
                self._last_state = "inactive_or_unconfirmed_ev"
                self._last_result = {}
                return
            if not self._hass.services.has_service("ohme", "list_charge_slots"):
                self._last_state = "native_ohme_service_unavailable"
                return
            self._last_attempt = dt_util.now()
            response = await self._hass.services.async_call(
                "ohme",
                "list_charge_slots",
                {"config_entry": entry_id},
                blocking=True,
                return_response=True,
            )
            observed_at = dt_util.now()
            normalized = observe_ohme_slot_response(
                response,
                now=observed_at,
                timezone=self._hass.config.time_zone,
            )
            self._last_result = normalized
            self._last_success = observed_at
            self._last_error = None
            self._last_state = normalized["status"]
        except asyncio.CancelledError:
            raise
        except Exception as error:  # Optional diagnostics must never affect control.
            self._last_error = type(error).__name__
            self._last_state = "read_only_observation_failed"

    async def async_shutdown(self) -> None:
        """Unsubscribe and cancel only the independent read-only worker."""
        self._closed = True
        if callable(self._unsubscribe):
            self._unsubscribe()
            self._unsubscribe = None
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
