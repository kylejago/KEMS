"""Restart-safe, read-only KEMS/Core lifecycle observation history.

A KEMS setup is not proof of a Core restart: it can be an integration reload.
HA start/stop bus events are stronger lifecycle observations, but still do not
prove the root cause of an observation gap or any meter reading during downtime.
Only event type and UTC timestamp are stored; no actor IDs or service arguments.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

LOGGER = logging.getLogger(__name__)
MAX_EVENTS = 120
KEEP_DAYS = 30
ALLOWED_EVENTS = frozenset(
    {
        "kems_setup",
        "core_started_event_observed",
        "core_stopping_event_observed",
        "core_restart_service_requested",
    }
)


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.astimezone(UTC) if stamp.tzinfo is not None else None


def validated_lifecycle_events(
    payload: Any, *, now: datetime
) -> list[dict[str, str]]:
    """Allow only bounded, recent, strictly typed and timezone-aware evidence."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return []
    result: list[dict[str, str]] = []
    for raw in payload.get("events", [])[-MAX_EVENTS:]:
        if not isinstance(raw, dict) or raw.get("kind") not in ALLOWED_EVENTS:
            continue
        instant = _parse(raw.get("observed_at"))
        if (
            instant is None
            or instant > now.astimezone(UTC) + timedelta(seconds=15)
            or instant < now.astimezone(UTC) - timedelta(days=KEEP_DAYS)
        ):
            continue
        result.append(
            {"kind": raw["kind"], "observed_at": instant.isoformat()}
        )
    return sorted(result, key=lambda row: row["observed_at"])[-MAX_EVENTS:]


class CoreLifecycleEvidenceRecorder:
    """Observe lifecycle events; never influence KEMS dispatch or updates."""

    def __init__(self, hass: Any, entry_id: str) -> None:
        self._store = Store(hass, 1, f"kems.{entry_id}.core_lifecycle_evidence")
        self._events: list[dict[str, str]] = []
        self._restored_events = 0
        self._last_storage_error: str | None = None

    async def async_load(self) -> None:
        """Restore safely and record this setup even after a manual reload."""
        try:
            raw = await self._store.async_load()
            self._events = validated_lifecycle_events(raw, now=dt_util.now())
            self._restored_events = len(self._events)
        except Exception as error:
            self._last_storage_error = type(error).__name__
            LOGGER.warning("Optional KEMS lifecycle evidence restore failed: %s", error)
        self.observe("kems_setup")
        # Persist setup immediately so a later crash/restart still leaves a
        # bounded marker. This is not a physical control prerequisite.
        await self.async_save()

    def observe(self, kind: str, *, now: datetime | None = None) -> None:
        """Record a Core bus event without claiming Core or KEMS caused it."""
        if kind not in ALLOWED_EVENTS:
            return
        instant = now or dt_util.now()
        self._events.append(
            {"kind": kind, "observed_at": instant.astimezone(UTC).isoformat()}
        )
        self._events = self._events[-MAX_EVENTS:]
        try:
            self._store.async_delay_save(self._payload, 5)
        except Exception as error:
            self._last_storage_error = type(error).__name__

    def _payload(self) -> dict[str, Any]:
        return {"schema_version": 1, "events": list(self._events)}

    async def async_save(self) -> None:
        """Best-effort evidence flush; failure must not affect energy control."""
        try:
            await self._store.async_save(self._payload())
        except Exception as error:
            self._last_storage_error = type(error).__name__
            LOGGER.warning("Optional KEMS lifecycle evidence save failed: %s", error)

    @property
    def events(self) -> list[dict[str, str]]:
        return list(self._events)

    @property
    def status(self) -> dict[str, Any]:
        return {
            "read_only": True,
            "scope": "persistent_kems_and_core_lifecycle_markers",
            "events": list(self._events[-MAX_EVENTS:]),
            "restored_events": self._restored_events,
            "last_storage_error_type": self._last_storage_error,
            "kems_setup_is_not_proof_of_core_restart": True,
            "core_events_only_observed_while_kems_listener_active": True,
            "missing_event_does_not_prove_no_restart": True,
            "contains_actor_identifiers": False,
            "meter_or_tariff_authority": False,
        }
