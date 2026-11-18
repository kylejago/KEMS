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
    intelligent_slot_message,
    morning_report_due,
    notify_entity_readiness,
    regular_offpeak_message,
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
        self._tracked_power_down: dict[str, Any] = {}
        self._intelligent_slot_last_state: str | None = None
        self._regular_offpeak_last_state: str | None = None
        self._slot_setup_at: datetime | None = None
        self._storage_healthy = True
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
        family_readiness = self._target_readiness(family)
        private_readiness = self._target_readiness(private)
        legacy = self._legacy_conflicts()
        daily_keys = sorted(
            key for key in self._delivered if key.startswith("recap:daily:")
        )
        weekly_keys = sorted(
            key for key in self._delivered if key.startswith("recap:weekly:")
        )
        slot_keys = sorted(
            key for key in self._delivered if key.startswith("intelligent-slot:")
        )
        regular_keys = sorted(
            key for key in self._delivered if key.startswith("regular-offpeak:")
        )
        return {
            "enabled": self.enabled,
            "family_target": family,
            "private_target": private,
            "family_target_available": family_readiness["send_eligible"],
            "private_target_available": private_readiness["send_eligible"],
            "family_target_status": family_readiness["status"],
            "private_target_status": private_readiness["status"],
            "family_target_ha_state": family_readiness["ha_state"],
            "private_target_ha_state": private_readiness["ha_state"],
            "daily_enabled": self.options.get(CONF_WHATSAPP_DAILY) is True,
            "weekly_enabled": self.options.get(CONF_WHATSAPP_WEEKLY) is True,
            "joined_events_enabled": self.options.get(CONF_WHATSAPP_SESSIONS) is True,
            "intelligent_slot_alerts_enabled": (
                self.options.get(CONF_WHATSAPP_SESSIONS) is True
            ),
            "intelligent_slot_last_observed_state": self._intelligent_slot_last_state,
            "intelligent_slot_transitions_accepted": len(slot_keys),
            "regular_offpeak_last_observed_state": self._regular_offpeak_last_state,
            "regular_offpeak_transitions_accepted": len(regular_keys),
            "legacy_intelligent_slot_mobile_automations": (
                self._legacy_intelligent_slot_mobile_automations()
            ),
            "private_alerts_enabled": self.options.get(CONF_WHATSAPP_PRIVATE) is True,
            "legacy_automation_conflicts": legacy,
            "last_error": self._last_error,
            "delivery_store_healthy": self._storage_healthy,
            "tracked_joined_power_down_event": bool(self._tracked_power_down),
            "last_attempt": self._last_attempt,
            "last_success": self._last_delivered,
            "successful_deliveries_since_setup": self._delivered_count,
            "durably_recorded_delivery_keys": len(self._delivered),
            "scheduled_daily_recaps_accepted": len(daily_keys),
            "scheduled_weekly_recaps_accepted": len(weekly_keys),
            "last_scheduled_daily_recap_key": daily_keys[-1] if daily_keys else None,
            "last_scheduled_weekly_recap_key": (
                weekly_keys[-1] if weekly_keys else None
            ),
            "schedule_delivery_basis": (
                "HA notify service accepted and persisted; recipient receipt "
                "is not independently verified"
            ),
            "reporting_only": True,
            "control_dependency": False,
            "migration_note": (
                "No legacy KEMS WhatsApp automation detected; no separate "
                "YAML or notification automation is required."
                if not legacy
                else "An active legacy KEMS WhatsApp automation was detected; "
                "KEMS suppresses duplicate notifications until it is disabled."
            ),
        }

    def _legacy_intelligent_slot_mobile_automations(self) -> list[str]:
        """Detect the two supplied automations without disabling them."""
        aliases = {
            "octopus intelligent slot notification on",
            "octopus intelligent slot end notification",
        }
        return sorted(
            state.entity_id
            for state in self.hass.states.async_all("automation")
            if state.state == "on"
            and str(state.attributes.get("friendly_name") or "").strip().lower()
            in aliases
        )

    def _target_readiness(self, target: Any) -> dict[str, Any]:
        state = (
            self.hass.states.get(target)
            if isinstance(target, str) and target.startswith("notify.")
            else None
        )
        return notify_entity_readiness(target, state)

    def _target_available(self, target: Any) -> bool:
        return self._target_readiness(target)["send_eligible"]

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
                "kems_whatsapp" in text or "kems whatsapp" in text
            ) and state.state == "on":
                conflicts.append(state.entity_id)
        return sorted(conflicts)

    async def async_setup(self) -> None:
        if not self.enabled:
            return
        try:
            stored = await self._store.async_load() or {}
            slot_state = stored.get("intelligent_slot_last_state")
            if slot_state in {"on", "off"}:
                self._intelligent_slot_last_state = slot_state
            regular_state = stored.get("regular_offpeak_last_state")
            if regular_state in {"on", "off"}:
                self._regular_offpeak_last_state = regular_state
            tracked = stored.get("tracked_power_down")
            if isinstance(tracked, dict):
                self._tracked_power_down = {
                    key: tracked.get(key)
                    for key in ("event_id", "start", "end", "joined")
                }
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
            self._storage_healthy = False
            self._last_error = f"delivery_store_unavailable: {type(err).__name__}"
            LOGGER.warning("KEMS WhatsApp disabled: could not load delivery state")
            return

        self._slot_setup_at = dt_util.now()

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
                    "tracked_power_down": self._tracked_power_down,
                    "intelligent_slot_last_state": self._intelligent_slot_last_state,
                    "regular_offpeak_last_state": self._regular_offpeak_last_state,
                }
            )
        except (OSError, ValueError, TypeError) as err:
            self._storage_healthy = False
            self._last_error = f"delivery_state_save_failed: {type(err).__name__}"
            LOGGER.warning("KEMS WhatsApp could not persist dedupe state")
            return False
        return True

    async def _send(
        self, key: str, message: str, *, private: bool, now: datetime
    ) -> bool:
        if not self._storage_healthy:
            return False
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

    async def async_send_test(self, *, private: bool) -> bool:
        """User-invoked test; bypasses scheduled-message deduplication only."""
        if not self.enabled or not self._storage_healthy:
            self._last_error = "whatsapp_notifications_disabled_or_store_unavailable"
            return False
        now = dt_util.now()
        destination = "Private" if private else "Family"
        message = (
            f"🧪 *KEMS — {destination} WhatsApp Test*\n"
            "✅ This test was requested using the KEMS Home Assistant button.\n"
            "📱 The configured notification route accepted the message.\n"
            "ℹ️ Automatic event notifications and scheduled reports are unchanged."
        )
        async with self._lock:
            return await self._send(
                f"manual-test:{destination.lower()}:{now.isoformat()}",
                message,
                private=private,
                now=now,
            )

    def _bill_equivalent_periods(self) -> Any:
        """Read the same canonical energy costs shown on the KEMS dashboard."""
        state = self.hass.states.get("sensor.kems_energy_cost_comparison")
        return state.attributes.get("periods") if state is not None else None

    async def async_send_test_all(self) -> bool:
        """Manually send a recorded recap and clearly marked example alerts.

        This never changes real event status, report deduplication or control.
        """
        if not self.enabled or not self._storage_healthy:
            self._last_error = "whatsapp_notifications_disabled_or_store_unavailable"
            return False
        now = dt_util.now()
        data = getattr(self.coordinator, "data", None)
        periods = getattr(data, "periods", {}) if data is not None else {}
        snapshot = getattr(data, "snapshot", None)
        standing = getattr(snapshot, "electricity_standing_charge", None)
        _, recap = completed_period_message(
            periods,
            now,
            weekly=False,
            standing_charge_pence_per_day=standing,
            bill_equivalent_periods=self._bill_equivalent_periods(),
        )
        examples = [
            (
                False,
                "📊 *KEMS WhatsApp Test — Yesterday's Totals*\n"
                + recap
                + "\n\n🧪 TEST ONLY — no scheduled report recorded.",
            ),
            (
                False,
                "🧪 *KEMS Power Down — Example Notification*\n"
                "⚡ Sample confirmed-event start message.\n"
                "No actual Power Down session has been started or joined.\n"
                "💷 Supplier reward: not verified (example only).",
            ),
            (
                False,
                "🧪 *KEMS Happy Hour — Example Notification*\n"
                "🟢 Sample confirmed-event start message.\n"
                "No actual Happy Hour session has been started or joined.\n"
                "🎁 Refund: estimated only when verified meter evidence exists.",
            ),
            (
                False,
                "🧪 *KEMS Octopus Intelligent — Cheap Slot Active*\n"
                "🕒 Start: 23:30\n🕓 End: TBC\n"
                "Sample active-slot alert only. No real slot has been started.",
            ),
            (
                False,
                "🧪 *KEMS Octopus Intelligent — Cheap Slot Ended*\n"
                "🕒 End: 05:30\n"
                "Sample ended-slot alert only. No real slot has ended.",
            ),
            (
                True,
                "🧪 *KEMS Private Technical Alert — Example*\n"
                "🚨 Demonstration alert — no real fault is asserted.\n"
                "✅ Energy control and scheduled alerts are unchanged.",
            ),
        ]
        async with self._lock:
            for index, (private, message) in enumerate(examples, start=1):
                if not await self._send(
                    f"manual-test-all:{now.isoformat()}:{index}",
                    message,
                    private=private,
                    now=now,
                ):
                    return False
        return True

    async def _regular_offpeak_alerts(self, now: datetime) -> None:
        """Announce actual normal off-peak boundaries, not guessed rate windows."""
        entity_id = getattr(self.coordinator.entities, "off_peak", None)
        state = self.hass.states.get(entity_id) if entity_id else None
        value = getattr(state, "state", None)
        if value not in {"on", "off"}:
            return
        if self._regular_offpeak_last_state is None:
            self._regular_offpeak_last_state = value
            await self._persist()
            return
        if value == self._regular_offpeak_last_state:
            return
        changed_at = getattr(state, "last_changed", None)
        if not isinstance(changed_at, datetime) or changed_at.tzinfo is None:
            return
        if self._slot_setup_at is None or changed_at < self._slot_setup_at:
            self._regular_offpeak_last_state = value
            await self._persist()
            return
        proposal = regular_offpeak_message(
            state=value, changed_at=changed_at, now=now
        )
        if proposal is None:
            return
        key, message = proposal
        if await self._send(key, message, private=False, now=now):
            self._regular_offpeak_last_state = value
            await self._persist()

    async def _intelligent_slot_alerts(self, now: datetime) -> None:
        """Track real binary-sensor transitions with a persistent baseline.

        Ignore unknown/unavailable and integration-startup initial state.
        Never infer slots from tariff prices or a next-slot timestamp.
        """
        entity_id = getattr(self.coordinator.entities, "intelligent_slot", None)
        state = self.hass.states.get(entity_id) if entity_id else None
        value = getattr(state, "state", None)
        if value not in {"on", "off"}:
            return
        if self._intelligent_slot_last_state is None:
            self._intelligent_slot_last_state = value
            await self._persist()
            return
        if value == self._intelligent_slot_last_state:
            return
        # The normal tariff sensor has its own independent start/end alert.
        # Avoid a duplicate Intelligent notification at the same boundary.
        offpeak_entity = getattr(self.coordinator.entities, "off_peak", None)
        offpeak_state = self.hass.states.get(offpeak_entity) if offpeak_entity else None
        normal_value = getattr(offpeak_state, "state", None)
        normal_changed = getattr(offpeak_state, "last_changed", None)
        normal_just_ended = bool(
            normal_value == "off"
            and isinstance(normal_changed, datetime)
            and normal_changed.tzinfo is not None
            and 0 <= (now - normal_changed).total_seconds() <= 300
        )
        if (value == "on" and normal_value == "on") or (
            value == "off" and normal_just_ended
        ):
            self._intelligent_slot_last_state = value
            await self._persist()
            return
        changed_at = getattr(state, "last_changed", None)
        if not isinstance(changed_at, datetime) or changed_at.tzinfo is None:
            return
        # A change during HA/KEMS downtime is not a witnessed start/end.
        # Rebaseline rather than send a misleading retroactive event.
        if self._slot_setup_at is None or changed_at < self._slot_setup_at:
            self._intelligent_slot_last_state = value
            await self._persist()
            return
        end_entity = getattr(self.coordinator.entities, "offpeak_end", None)
        end_state = self.hass.states.get(end_entity) if end_entity else None
        proposal = intelligent_slot_message(
            state=value,
            changed_at=changed_at,
            now=now,
            end_time=getattr(end_state, "state", None),
        )
        if proposal is None:
            return
        key, message = proposal
        if await self._send(key, message, private=False, now=now):
            self._intelligent_slot_last_state = value
            await self._persist()

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
        stale_tariff = tuple(getattr(snapshot, "tariff_stale_fields", ()) or ())
        if (
            stale_tariff
            and getattr(control, "control_enabled", False)
            and not getattr(control, "commissioned", False)
        ):
            warnings["tariff_commissioning_blocked"] = (
                "KEMS energy control is blocked by tariff-source evidence: "
                + ", ".join(stale_tariff[:5])
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
                    f"✅ *KEMS — Warning cleared*\n"
                    f"{key.replace('_', ' ').title()} has recovered.",
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
                    f"🚨 *KEMS — Technical warning*\n⚠️ {description}.\n"
                    "Persisting for at least 5 minutes. "
                    "Energy control operates independently.",
                    private=True,
                    now=now,
                ):
                    self._warning_alerted[key] = first.isoformat()
                    dirty = True
        if dirty:
            await self._persist()

    async def _tick(self, now: datetime) -> None:
        if (
            not self.enabled
            or not self._storage_healthy
            or self._cancel is None
            or self._lock.locked()
        ):
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
                        active = {
                            "joined": True,
                            "event_id": power_down.saving_session_id,
                            "start": power_down.saving_session_start,
                            "end": power_down.saving_session_end,
                        }
                        joined.append(active)
                        stored = {
                            key: (
                                value.isoformat()
                                if isinstance(value, datetime)
                                else value
                            )
                            for key, value in active.items()
                        }
                        if stored != self._tracked_power_down:
                            self._tracked_power_down = stored
                            await self._persist()
                    elif self._tracked_power_down.get("joined") is True:
                        # The provider drops a finished event immediately.
                        # Only a previously joined event may produce an
                        # ending alert, never a retroactive start or plan.
                        previous = self._tracked_power_down
                        try:
                            end = datetime.fromisoformat(str(previous["end"]))
                        except (ValueError, TypeError):
                            end = None
                        if (
                            end is not None
                            and end.tzinfo is not None
                            and end <= now < end + timedelta(minutes=2)
                        ):
                            joined.append(previous)
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
                if self.options.get(CONF_WHATSAPP_SESSIONS) is True:
                    await self._regular_offpeak_alerts(now)
                    await self._intelligent_slot_alerts(now)
                for weekly, option in (
                    (False, CONF_WHATSAPP_DAILY),
                    (True, CONF_WHATSAPP_WEEKLY),
                ):
                    if self.options.get(option) is True and morning_report_due(
                        now, weekly=weekly
                    ):
                        key, message = completed_period_message(
                            data.periods,
                            now,
                            weekly=weekly,
                            standing_charge_pence_per_day=getattr(
                                data.snapshot, "electricity_standing_charge", None
                            ),
                            bill_equivalent_periods=self._bill_equivalent_periods(),
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
