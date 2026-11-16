"""Optional KEMS notifications through Home Assistant notify entities.

Isolated from KEMS control, planning, financial history and FoxESS writes.
All send operations happen in separate HA tasks; missing notifiers fail open
for energy operation and fail closed for notifications.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_WHATSAPP_DAILY,
    CONF_WHATSAPP_ENABLED,
    CONF_WHATSAPP_FAMILY_ENTITY,
    CONF_WHATSAPP_PRIVATE,
    CONF_WHATSAPP_PRIVATE_ENTITY,
    CONF_WHATSAPP_SESSIONS,
    CONF_WHATSAPP_WEEKLY,
    STORAGE_NAMESPACE,
)
from .happy_hour_auto_join import verified_octopus_joined_bookings
from .kems_core.whatsapp_message_plans import (
    completed_period_message,
    event_notifications,
    morning_report_due,
)

LOGGER = logging.getLogger(__name__)

_WARNING_PERSISTENCE = timedelta(minutes=5)
_SENT_MAX = 500


class KEMSWhatsAppNotifications:
    """A bounded optional timer; never called from the control scan path."""

    def __init__(self, hass: HomeAssistant, entry: Any, coordinator: Any) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self.options = dict(entry.options)
        self._store = Store(hass, 1, f"{STORAGE_NAMESPACE}_whatsapp_{entry.entry_id}")
        self._cancel: Any = None
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._delivered: dict[str, str] = {}
        self._warning_since: dict[str, str] = {}
        self._warning_alerted: dict[str, str] = {}
        self._last_error: str | None = None
        self._last_delivered: str | None = None
        self._last_attempt: str | None = None
        self._delivered_count = 0

    @property
    def enabled(self) -> bool:
        return self.options.get(CONF_WHATSAPP_ENABLED) is True

    @property
    def status(self) -> dict[str, Any]:
        family = self.options.get(
            CONF_WHATSAPP_FAMILY_ENTITY, "notify.whatsapp_message"
        )
        private = self.options.get(
            CONF_WHATSAPP_PRIVATE_ENTITY, "notify.kems_private_alerts_message"
        )
        return {
            "enabled": self.enabled,
            "family_target": family,
            "private_target": private,
            "family_target_available": self._target_available(family),
            "private_target_available": self._target_available(private),
            "daily_enabled": self.options.get(CONF_WHATSAPP_DAILY) is True,
            "weekly_enabled": self.options.get(CONF_WHATSAPP_WEEKLY) is True,
            "joined_events_enabled": self.options.get(CONF_WHATSAPP_SESSIONS) is True,
            "private_alerts_enabled": self.options.get(CONF_WHATSAPP_PRIVATE) is True,
            "legacy_automation_conflicts": self._legacy_conflicts(),
            "last_error": self._last_error,
            "last_attempt": self._last_attempt,
            "last_success": self._last_delivered,
            "successful_deliveries_since_setup": self._delivered_count,
            "durably_recorded_delivery_keys": len(self._delivered),
            "reporting_only": True,
            "control_dependency": False,
            "migration_note": (
                "Disable/remove legacy kems_whatsapp.yaml automations to "
                "avoid duplicate messages; KEMS suppresses notifications "
                "if identifiable legacy KEMS WhatsApp automations are active."
            ),
        }

    def _target_available(self, target: Any) -> bool:
        if not isinstance(target, str) or not target.startswith("notify."):
            return False
        state = self.hass.states.get(target)
        return state is not None and state.state not in {
            "unknown",
            "unavailable",
        }

    def _legacy_conflicts(self) -> list[str]:
        conflicts: list[str] = []
        for state in self.hass.states.async_all("automation"):
            text = " ".join(
                str(value or "")
                for value in (
                    state.entity_id,
                    state.attributes.get("friendly_name"),
                    state.attributes.get("id"),
                )
            ).lower()
            if (
                ("kems_whatsapp" in text or "kems whatsapp" in text)
                and state.state == "on"
            ):
                conflicts.append(state.entity_id)
        return sorted(conflicts)

    async def async_setup(self) -> None:
        if not self.enabled:
            return
        try:
            stored = await self._store.async_load() or {}
            for field, name in (
                ("delivered", "_delivered"),
                ("warning_since", "_warning_since"),
                ("warning_alerted", "_warning_alerted"),
            ):
                value = stored.get(field)
                if isinstance(value, dict):
                    setattr(
                        self,
                        name,
                        {
                            str(k): str(v)
                            for k, v in value.items()
                            if isinstance(k, str) and isinstance(v, str)
                        },
                    )
        except (OSError, ValueError, TypeError) as err:
            # Persistence is an idempotency prerequisite. Never send if the
            # existing delivery store could not be loaded safely.
            self._last_error = f"delivery_store_unavailable: {type(err).__name__}"
            LOGGER.warning("KEMS WhatsApp disabled: could not load delivery state")
            return

        @callback
        def _timer(now: datetime) -> None:
            task = self.hass.async_create_task(self._tick(now))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        self._cancel = async_track_time_interval(
            self.hass, _timer, timedelta(minutes=1)
        )
        _timer(dt_util.now())

    async def async_shutdown(self) -> None:
        if callable(self._cancel):
            self._cancel()
            self._cancel = None
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _persist(self) -> bool:
        # Limit storage indefinitely to prevent old event records exploding
        # over years of WhatsApp notifications.
        if len(self._delivered) > _SENT_MAX:
            ordered = sorted(self._delivered.items(), key=lambda x: x[1])
            self._delivered = dict(ordered[-_SENT_MAX:])
        try:
            await self._store.async_save(
                {
                    "delivered": self._delivered,
                    "warning_since": self._warning_since,
                    "warning_alerted": self._warning_alerted,
                }
            )
        except (OSError, ValueError, TypeError) as err:
            self._last_error = f"delivery_state_save_failed: {type(err).__name__}"
            LOGGER.warning("KEMS WhatsApp could not persist dedupe state")
            return False
        return True

    async def _send(
        self, key: str, message: str, *, private: bool, now: datetime
    ) -> bool:
        if key in self._delivered:
            return True
        target = self.options.get(
            CONF_WHATSAPP_PRIVATE_ENTITY if private else CONF_WHATSAPP_FAMILY_ENTITY
        )
        self._last_attempt = now.isoformat()
        if not self._target_available(target):
            self._last_error = "configured_notify_entity_unavailable"
            return False
        if not self.hass.services.has_service("notify", "send_message"):
            self._last_error = "notify_send_message_not_registered"
            return False
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {"message": message},
                blocking=True,
                target={"entity_id": target},
            )
        except Exception as err:  # HA notify integrations may raise many types.
            self._last_error = f"notify_delivery_error: {type(err).__name__}"
            LOGGER.warning(
                "KEMS WhatsApp notification failed (%s); energy control unaffected",
                type(err).__name__,
            )
            return False
        # Record only after Home Assistant accepted the send. Delivery to
        # phones is external and cannot be independently guaranteed by KEMS.
        self._delivered[key] = now.isoformat()
        self._delivered_count += 1
        self._last_delivered = now.isoformat()
        self._last_error = None
        await self._persist()
        return True

    def _current_warnings(self) -> dict[str, str]:
        data = getattr(self.coordinator, "data", None)
        if data is None:
            return {}
        control = data.control
        snapshot = data.snapshot
        warnings: dict[str, str] = {}
        soc = getattr(snapshot, "battery_soc", None)
        if isinstance(soc, (float, int)) and 0 <= soc < 10:
            warnings["battery_below_hard_floor"] = (
                f"Physical battery SOC {soc:.1f}% is below the 10% safety floor"
            )
        if getattr(control, "eps_critical", False) is True:
            warnings["eps_critical"] = "EPS load is at a critical level"
        if (
            getattr(control, "control_enabled", False)
            and getattr(control, "commissioned", False)
            and getattr(control, "plan_safe", True) is False
        ):
            warnings["unsafe_control_plan"] = (
                "A commissioned KEMS control plan is unsafe"
            )
        if getattr(self.coordinator, "last_update_success", True) is False:
            warnings["coordinator_update_failed"] = (
                "KEMS coordinator data refresh is failing"
            )
        stale = tuple(getattr(snapshot, "stale_fields", ()) or ())
        if stale and getattr(control, "control_enabled", False):
            warnings["critical_source_stale"] = (
                "Critical KEMS source data is stale: " + ", ".join(stale[:5])
            )
        return warnings

    async def _private_alerts(self, now: datetime) -> None:
        warnings = self._current_warnings()
        dirty = False
        for key in list(self._warning_since):
            if key in warnings:
                continue
            old_start = self._warning_since.pop(key)
            dirty = True
            if key in self._warning_alerted:
                sent_start = self._warning_alerted[key]
                recovery_key = f"private:recovery:{key}:{sent_start}"
                recovered = await self._send(
                    recovery_key,
                    f"KEMS recovery: {key.replace('_', ' ')} has cleared.",
                    private=True,
                    now=now,
                )
                if recovered:
                    self._warning_alerted.pop(key, None)
            else:
                self._warning_alerted.pop(key, None)
            del old_start

        for key, description in warnings.items():
            if key not in self._warning_since:
                self._warning_since[key] = now.isoformat()
                dirty = True
            try:
                first = datetime.fromisoformat(self._warning_since[key])
            except ValueError:
                first = now
            if now - first >= _WARNING_PERSISTENCE and key not in self._warning_alerted:
                alert_key = f"private:warning:{key}:{first.isoformat()}"
                if await self._send(
                    alert_key,
                    f"KEMS important warning (persisting ≥5 minutes): {description}.",
                    private=True,
                    now=now,
                ):
                    self._warning_alerted[key] = first.isoformat()
                    dirty = True
        if dirty:
            await self._persist()

    async def _tick(self, now: datetime) -> None:
        if not self.enabled or self._cancel is None or self._lock.locked():
            return
        async with self._lock:
            try:
                if self._legacy_conflicts():
                    self._last_error = "legacy_kems_whatsapp_automations_active"
                    return
                data = getattr(self.coordinator, "data", None)
                if data is None:
                    return
                if self.options.get(CONF_WHATSAPP_SESSIONS) is True:
                    power_down = data.snapshot
                    joined: list[dict[str, Any]] = []
                    if power_down.saving_session_joined is True:
                        joined.append(
                            {
                                "joined": True,
                                "event_id": power_down.saving_session_id,
                                "start": power_down.saving_session_start,
                                "end": power_down.saving_session_end,
                            }
                        )
                    happy = [
                        {**row, "joined": True}
                        for row in verified_octopus_joined_bookings(self.hass, now=now)
                    ]
                    for category, events in (
                        ("Power Down", joined),
                        ("Happy Hour", happy),
                    ):
                        for key, message in event_notifications(
                            category=category,
                            joined_events=events,
                            now=now,
                            sent_keys=self._delivered,
                        ):
                            await self._send(key, message, private=False, now=now)
                for weekly, option in (
                    (False, CONF_WHATSAPP_DAILY),
                    (True, CONF_WHATSAPP_WEEKLY),
                ):
                    if self.options.get(option) is True and morning_report_due(
                        now, weekly=weekly
                    ):
                        key, message = completed_period_message(
                            data.periods, now, weekly=weekly
                        )
                        await self._send(key, message, private=False, now=now)
                if self.options.get(CONF_WHATSAPP_PRIVATE) is True:
                    await self._private_alerts(now)
            except Exception:
                self._last_error = "notification_tick_failed"
                LOGGER.exception(
                    "KEMS optional WhatsApp reporter failed; no effect on control"
                )


async def async_setup_kems_whatsapp(
    hass: HomeAssistant, entry: Any, coordinator: Any
) -> None:
    """Attach one independently scheduled optional reporter per KEMS entry."""
    reporter = KEMSWhatsAppNotifications(hass, entry, coordinator)
    coordinator._kems_whatsapp_reporter = reporter
    try:
        await reporter.async_setup()
    except Exception:
        LOGGER.exception(
            "KEMS optional WhatsApp setup failed; energy control continues"
        )


async def async_unload_kems_whatsapp(coordinator: Any) -> None:
    reporter = getattr(coordinator, "_kems_whatsapp_reporter", None)
    if reporter is not None:
        await reporter.async_shutdown()
        coordinator._kems_whatsapp_reporter = None
