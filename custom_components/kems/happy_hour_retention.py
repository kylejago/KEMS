"""Durable automatic Weekend Happy Hour evidence for KEMS.

BottlecapDave's live Power Up coordinator can stop exposing a joined event after
completion. KEMS therefore retains the last confidently classified automatic
Happy Hour in Home Assistant storage and may reuse that evidence when the live
feed becomes empty. Ambiguous live Power Up data always wins fail-safe. A newer
manual fallback is also preserved unless KEMS has stronger evidence that it
successfully booked a specific Weekend Happy Hour through Octopus.
"""

# ruff: noqa: E501  # Embedded Lovelace/Jinja lines are intentionally verbatim.

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from .const import DOMAIN, STORAGE_NAMESPACE

STORAGE_VERSION = 1
_MAX_RETAINED_PLAN_AGE = timedelta(days=35)
_AMBIGUOUS_PREFIX = "ambiguous_"
_NO_EVENT_STATUSES = {
    "no_confident_weekend_happy_hour",
    "power_up_source_unavailable",
}
_RECORDERS: dict[tuple[int, str], HappyHourEvidenceRecorder] = {}


def _dt(value: Any) -> datetime | None:
    """Return an aware UTC timestamp when possible."""
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


def _serialise_event(event: Mapping[str, Any], captured_at: datetime) -> dict[str, Any]:
    """Return the JSON-safe automatic-event evidence stored by KEMS."""
    output: dict[str, Any] = {}
    for key in (
        "source",
        "automatic_source_supported",
        "source_kind",
        "source_entity",
        "source_account",
        "classification_basis",
        "confidence",
        "event_ids",
        "event_code",
        "booking_authoritative",
        "booking_source",
        "duration_hours",
        "fair_use_cap_kwh",
    ):
        if key in event:
            output[key] = event[key]
    start = _dt(event.get("start"))
    end = _dt(event.get("end"))
    if start is not None:
        output["start"] = start.isoformat()
    if end is not None:
        output["end"] = end.isoformat()
    output["captured_at"] = captured_at.astimezone(UTC).isoformat()
    return output


def _same_window(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Return whether two event-shaped mappings identify the same time window."""
    left_start = _dt(left.get("start"))
    left_end = _dt(left.get("end"))
    right_start = _dt(right.get("start"))
    right_end = _dt(right.get("end"))
    return bool(
        left_start is not None
        and left_end is not None
        and right_start is not None
        and right_end is not None
        and abs((left_start - right_start).total_seconds()) <= 90
        and abs((left_end - right_end).total_seconds()) <= 90
    )


def _auto_join_booking_event(hass: Any, now: datetime) -> dict[str, Any] | None:
    """Return one KEMS-confirmed booking as dispatch-safe Octopus evidence.

    Octopus Energy 19.1 retains an event ``code`` on joined Power Up events.
    Historical KEMS discovery deliberately rejects coded events because older
    generic free-electricity events used the same feed. Alpha9.40 has stronger
    evidence after the supported Weekend Happy Hour join service returns success:
    the exact code and window that KEMS itself booked. Bridge that confirmed
    booking into the existing retained-event authority rather than weakening the
    generic coded-event classifier.
    """
    try:
        from . import happy_hour_auto_join
    except ImportError:
        return None

    controllers = getattr(happy_hour_auto_join, "_CONTROLLERS", {})
    if not isinstance(controllers, Mapping):
        return None
    matches = [
        controller
        for key, controller in controllers.items()
        if isinstance(key, tuple) and key and key[0] == id(hass)
    ]
    if len(matches) != 1:
        return None

    state = getattr(matches[0], "state", None)
    if not isinstance(state, Mapping) or state.get("status") != "booked":
        return None
    code = str(state.get("booked_event_code") or "").strip()
    start = _dt(state.get("booked_start"))
    end = _dt(state.get("booked_end"))
    if not code or start is None or end is None or end <= start:
        return None
    if end < now - _MAX_RETAINED_PLAN_AGE:
        return None

    duration = max((end - start).total_seconds() / 3600.0, 0.0)
    reward_hours = 2 if duration >= 1.5 else 1
    return {
        "enabled": True,
        "source": "octopus_energy",
        "automatic_source_supported": True,
        "automatic_status": "detected_kems_booking",
        "source_kind": "kems_auto_join_booking",
        "source_entity": state.get("source_entity"),
        "source_account": state.get("source_account"),
        "classification_basis": (
            "KEMS-confirmed Weekend Happy Hour booking via the supported "
            "Octopus join service"
        ),
        "confidence": "confirmed_booking",
        "event_ids": [code],
        "event_code": code,
        "booking_authoritative": True,
        "booking_source": "kems_auto_join",
        "start": start,
        "end": end,
        "duration_hours": reward_hours,
        "fair_use_cap_kwh": 16.0 * reward_hours,
    }


def retained_happy_hour_result(
    live: Mapping[str, Any],
    retained: Mapping[str, Any] | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    """Apply retained automatic evidence only when doing so is unambiguous."""
    result = dict(live)
    if result.get("source") == "octopus_energy":
        result["automatic_evidence"] = "live"
        return result

    status = str(result.get("automatic_status") or "")
    if status.startswith(_AMBIGUOUS_PREFIX):
        result["retained_automatic_event_available"] = bool(retained)
        return result
    if status not in _NO_EVENT_STATUSES or not retained:
        return result

    retained_start = _dt(retained.get("start"))
    retained_end = _dt(retained.get("end"))
    if retained_start is None or retained_end is None or retained_end <= retained_start:
        return result
    if retained_end < now - _MAX_RETAINED_PLAN_AGE:
        result["retained_automatic_event_available"] = True
        result["retained_automatic_event_stale"] = True
        return result

    manual_start = _dt(result.get("start"))
    manual_end = _dt(result.get("end"))
    manual_current_or_future = bool(
        result.get("enabled")
        and manual_start is not None
        and manual_end is not None
        and manual_end > now
    )
    authoritative_booking = bool(retained.get("booking_authoritative"))
    if (
        manual_current_or_future
        and not _same_window(result, retained)
        and not authoritative_booking
    ):
        result["retained_automatic_event_available"] = True
        result["retained_automatic_event_superseded_by_manual"] = True
        return result

    if now < retained_start:
        retained_status = "retained_upcoming"
    elif now < retained_end:
        retained_status = "retained_active"
    else:
        retained_status = "retained_completed"

    output = dict(retained)
    output.update(
        {
            "enabled": True,
            "source": "octopus_energy",
            "automatic_source_supported": True,
            "automatic_status": retained_status,
            "source_kind": "retained_octopus_evidence",
            "retained_source_kind": retained.get("source_kind"),
            "automatic_evidence": (
                "kems_booking" if authoritative_booking else "retained"
            ),
            "evidence_retained": True,
            "retained_at": retained.get("captured_at"),
        }
    )
    output.pop("fallback_reason", None)
    output["start"] = retained_start
    output["end"] = retained_end
    return output


class HappyHourEvidenceRecorder:
    """Persist the last confidently detected automatic Happy Hour."""

    def __init__(self, hass: Any, storage_key: str) -> None:
        from homeassistant.helpers.storage import Store

        self._hass = hass
        self._store = Store(hass, STORAGE_VERSION, storage_key)
        self._retained: dict[str, Any] | None = None
        self._loaded = False
        self._loading = False
        self._last_signature: tuple[Any, ...] | None = None

    @property
    def retained(self) -> dict[str, Any] | None:
        """Return a copy of retained JSON-safe evidence."""
        return dict(self._retained) if self._retained else None

    async def _async_load_once(self) -> None:
        try:
            data = await self._store.async_load()
            last_event = data.get("last_event") if isinstance(data, Mapping) else None
            if isinstance(last_event, Mapping) and self._retained is None:
                self._retained = dict(last_event)
                self._last_signature = self._signature(self._retained)
        finally:
            self._loaded = True
            self._loading = False

    def ensure_loaded(self) -> None:
        """Start one non-blocking storage restore before planning continues."""
        if self._loaded or self._loading:
            return
        self._loading = True
        self._hass.async_create_task(self._async_load_once())

    @staticmethod
    def _signature(event: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            event.get("start"),
            event.get("end"),
            tuple(event.get("event_ids") or ()),
            event.get("source_account"),
        )

    def capture(self, event: Mapping[str, Any], now: datetime) -> None:
        """Persist newly observed automatic evidence once per event identity."""
        if event.get("source") != "octopus_energy":
            return
        status = str(event.get("automatic_status") or "")
        if not status.startswith("detected_"):
            return
        stored = _serialise_event(event, now)
        signature = self._signature(stored)
        if signature == self._last_signature:
            return
        self._retained = stored
        self._last_signature = signature
        self._hass.async_create_task(self._store.async_save({"last_event": stored}))

    def resolve(self, live: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        """Capture live or confirmed-booking evidence, then safely resolve it."""
        self.ensure_loaded()
        if live.get("source") == "octopus_energy":
            self.capture(live, now)
        else:
            booked = _auto_join_booking_event(self._hass, now)
            if booked is not None:
                self.capture(booked, now)
        return retained_happy_hour_result(live, self._retained, now=now)


def _entry_storage_identity(hass: Any, account_hint: str | None) -> str:
    """Prefer the single KEMS config-entry id, then the Octopus account hint."""
    config_entries = getattr(hass, "config_entries", None)
    async_entries = getattr(config_entries, "async_entries", None)
    if callable(async_entries):
        entries = list(async_entries(DOMAIN))
        if len(entries) == 1 and getattr(entries[0], "entry_id", None):
            return str(entries[0].entry_id)
    return account_hint or "default"


def _recorder_for(hass: Any, account_hint: str | None) -> HappyHourEvidenceRecorder:
    identity = _entry_storage_identity(hass, account_hint)
    key = (id(hass), identity)
    recorder = _RECORDERS.get(key)
    if recorder is None:
        recorder = HappyHourEvidenceRecorder(
            hass,
            f"{DOMAIN}.{identity}.{STORAGE_NAMESPACE}.happy_hour_auto",
        )
        _RECORDERS[key] = recorder
    return recorder


def install_happy_hour_retention() -> None:
    """Wrap Alpha8 automatic discovery with durable completed-event evidence."""
    from . import happy_hour_auto

    original = happy_hour_auto.automatic_happy_hour_event
    if getattr(original, "_kems_happy_hour_retention", False):
        return

    def automatic_with_retention(
        hass: Any,
        *,
        manual_options: Mapping[str, Any],
        saving_session_entity: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now_utc = (now or datetime.now(UTC)).astimezone(UTC)
        live = original(
            hass,
            manual_options=manual_options,
            saving_session_entity=saving_session_entity,
            now=now_utc,
        )
        account_hint = happy_hour_auto._account_hint_from_entity(saving_session_entity)
        return _recorder_for(hass, account_hint).resolve(live, now_utc)

    automatic_with_retention._kems_happy_hour_retention = True
    happy_hour_auto.automatic_happy_hour_event = automatic_with_retention

    old_line = "**Automatic source:** {{ auto or 'waiting for Octopus Power Up data' }}"
    new_lines = """**Automatic source:** {{ auto or 'waiting for Octopus Power Up data' }}  
          **Evidence:** {{ state_attr('sensor.kems_agile_happy_hour_plan', 'automatic_evidence') or 'live/manual fallback' }}"""
    happy_hour_auto._AUTO_DASHBOARD_INSERT = (
        happy_hour_auto._AUTO_DASHBOARD_INSERT.replace(
            old_line,
            new_lines,
        )
    )
