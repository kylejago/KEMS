"""Recover proven completed Happy Hour evidence across an Alpha8 upgrade.

Alpha8.3 introduced a retained completed-event record so Weekend Happy Hour can be
replayed by the ordinary Agile day ledger after the planning switch auto-clears.
An event which completed under the previous runtime can arrive after upgrade with
only the old configured start plus persisted Agile shadow audit evidence.

This migration is deliberately conservative: a disabled legacy event is recovered
only when the durable Agile shadow audit proves that ``happy_hour_charge`` ran
inside the booked window and that the next non-Happy-Hour decision occurred at or
after the booked end. A cancelled, ambiguous or merely configured event is never
invented as free energy.

The migration only updates KEMS config-entry metadata during shadow-store load.
It does not reload Home Assistant, alter dispatch, call a hardware service, or
enable physical writes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from . import shadow_validation as shadow
from .happy_hour import (
    CONF_HAPPY_HOUR_ENABLED,
    CONF_HAPPY_HOUR_START,
    happy_hour_duration_hours,
    parse_happy_hour_start,
)

_LAST_COMPLETED_START = "weekend_happy_hour_last_completed_start"
_LAST_COMPLETED_END = "weekend_happy_hour_last_completed_end"
_LAST_COMPLETED_DURATION = "weekend_happy_hour_last_completed_duration_hours"
_HAPPY_HOUR_CHARGE_MODE = "happy_hour_charge"


def _decision_time(value: Any) -> datetime | None:
    """Return one timezone-aware audit timestamp when possible."""
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def _legacy_completed_event(
    options: dict[str, Any],
    decisions: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any] | None:
    """Return safe completed-event metadata from durable legacy audit evidence."""
    if bool(options.get(CONF_HAPPY_HOUR_ENABLED, False)):
        return None
    if parse_happy_hour_start(options.get(_LAST_COMPLETED_START)) is not None:
        return None

    start = parse_happy_hour_start(options.get(CONF_HAPPY_HOUR_START))
    if start is None:
        return None
    start_utc = start.astimezone(UTC)
    duration = happy_hour_duration_hours(options)
    end_utc = start_utc + timedelta(hours=duration)
    if now.astimezone(UTC) < end_utc:
        return None

    timeline: list[tuple[datetime, str]] = []
    for item in decisions:
        if not isinstance(item, dict):
            continue
        timestamp = _decision_time(item.get("timestamp"))
        mode = str(item.get("dispatch_mode") or "")
        if timestamp is not None and mode:
            timeline.append((timestamp, mode))
    timeline.sort(key=lambda item: item[0])

    charge_times = [
        timestamp
        for timestamp, mode in timeline
        if start_utc <= timestamp < end_utc and mode == _HAPPY_HOUR_CHARGE_MODE
    ]
    if not charge_times:
        return None
    first_charge = charge_times[0]

    # A mode transition before the booked end means the event may have been
    # cancelled or interrupted. Decline recovery rather than overstate free energy.
    for timestamp, mode in timeline:
        if first_charge < timestamp < end_utc and mode != _HAPPY_HOUR_CHARGE_MODE:
            return None

    # Require explicit post-event audit evidence. This distinguishes an event that
    # genuinely ran through its booked end from a stale charge decision with no
    # observed completion transition.
    if not any(
        timestamp >= end_utc and mode != _HAPPY_HOUR_CHARGE_MODE
        for timestamp, mode in timeline
    ):
        return None

    return {
        _LAST_COMPLETED_START: start_utc.isoformat(),
        _LAST_COMPLETED_END: end_utc.isoformat(),
        _LAST_COMPLETED_DURATION: duration,
    }


def install_event_completion_migration() -> None:
    """Recover one proven legacy completion before the first Agile replay."""
    cls = shadow.ShadowValidationRecorder

    init = cls.__init__
    if not getattr(init, "_kems_event_completion_migration", False):
        original_init = init

        def init_with_entry_id(self, hass, entry_id: str) -> None:
            original_init(self, hass, entry_id)
            self._kems_event_completion_entry_id = str(entry_id)

        init_with_entry_id._kems_event_completion_migration = True
        cls.__init__ = init_with_entry_id

    load = cls.async_load
    if getattr(load, "_kems_event_completion_migration", False):
        return
    original_load = load

    async def load_with_completion_migration(self) -> None:
        await original_load(self)
        entry_id = getattr(self, "_kems_event_completion_entry_id", None)
        if not entry_id:
            return
        entry = self._hass.config_entries.async_get_entry(str(entry_id))
        if entry is None:
            return

        options = dict(entry.options)
        decisions = list(getattr(self, "_agile_decisions", []))
        recovered = _legacy_completed_event(
            options,
            decisions,
            now=datetime.now(UTC),
        )
        self._kems_event_completion_migration_recovered = recovered is not None
        if recovered is None:
            return

        # Do not call the normal runtime-options helper here: this load happens
        # during config-entry setup, before the first Agile replay, so an immediate
        # reload would recurse through setup. Updating entry options in-place is
        # sufficient for the replay manager to see the retained completion below.
        self._hass.config_entries.async_update_entry(
            entry,
            options={**options, **recovered},
        )

    load_with_completion_migration._kems_event_completion_migration = True
    cls.async_load = load_with_completion_migration
