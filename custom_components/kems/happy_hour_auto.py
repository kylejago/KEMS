"""Automatic Octopus Weekend Happy Hour discovery for Full KEMS Agile.

BottlecapDave HomeAssistant-OctopusEnergy 19.0.1 separates Power Down from
Power Up / Weekend Happy Hour events. The public Power Up event entity is
disabled by default, so KEMS prefers that public state when present and
otherwise reads the integration's read-only coordinator result. No Octopus
entities, settings, services or coordinator state are modified.

The upstream Home Assistant payload does not retain the GraphQL ``eventType``.
KEMS therefore applies a deliberately conservative classification: only
code-less, weekend, one/two-hour Power Up windows are eligible. Two consecutive
one-hour rewards are merged. Ambiguous non-contiguous candidates fail safe to
the existing manual Happy Hour input.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

from .happy_hour import (
    HAPPY_HOUR_FAIR_USE_KWH_PER_REWARD,
    manual_happy_hour_event,
)

_LONDON = ZoneInfo("Europe/London")
_OCTOPUS_DOMAIN = "octopus_energy"
_COORDINATOR_KEY = "POWER_UP_DOWN_COORDINATOR"
_POWER_UP_SUFFIX = "_octoplus_power_up_events"
_RECENT_GRACE = timedelta(hours=24)
_LOOKAHEAD = timedelta(days=21)
_CONTIGUOUS_TOLERANCE_SECONDS = 90


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


def _normalise_account(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _account_hint_from_entity(entity_id: str | None) -> str | None:
    """Extract the normalised account token from a configured Octopus entity."""
    if not entity_id:
        return None
    value = str(entity_id).lower()
    marker = "event.octopus_energy_"
    suffix = "_octoplus_power_down_events"
    if value.startswith(marker) and value.endswith(suffix):
        return _normalise_account(value[len(marker) : -len(suffix)])
    return None


def _event_dict(
    value: Any, *, source: str, source_entity: str | None
) -> dict[str, Any] | None:
    """Normalise one public-event dict or coordinator object."""
    if isinstance(value, Mapping):
        event_id = value.get("id")
        code = value.get("code")
        start = _dt(value.get("start"))
        end = _dt(value.get("end"))
        duration_value = value.get("duration_in_minutes")
    else:
        event_id = getattr(value, "id", None)
        code = getattr(value, "code", None)
        start = _dt(getattr(value, "start", None))
        end = _dt(getattr(value, "end", None))
        duration_value = getattr(value, "duration_in_minutes", None)
    if start is None or end is None or end <= start:
        return None
    try:
        duration_minutes = float(duration_value)
    except (TypeError, ValueError):
        duration_minutes = (end - start).total_seconds() / 60.0
    return {
        "id": str(event_id) if event_id is not None else None,
        "code": str(code).strip() if code not in (None, "") else None,
        "start": start,
        "end": end,
        "duration_minutes": duration_minutes,
        "source_kind": source,
        "source_entity": source_entity,
    }


def _public_power_up_events(
    hass: Any, account_hint: str | None
) -> tuple[list[dict[str, Any]], bool]:
    """Read enabled BottlecapDave Power Up event entities without mutation."""
    states = getattr(getattr(hass, "states", None), "async_all", None)
    if not callable(states):
        return [], False
    try:
        all_states = list(states())
    except TypeError:
        return [], False
    matching = []
    for state in all_states:
        entity_id = str(getattr(state, "entity_id", ""))
        lowered = entity_id.lower()
        if not lowered.startswith("event.octopus_energy_") or not lowered.endswith(
            _POWER_UP_SUFFIX
        ):
            continue
        if account_hint and account_hint not in _normalise_account(entity_id):
            continue
        matching.append(state)
    if len(matching) != 1:
        return [], bool(matching)
    state = matching[0]
    attributes = getattr(state, "attributes", {}) or {}
    raw_events = attributes.get("events") if isinstance(attributes, Mapping) else None
    if not isinstance(raw_events, list):
        return [], True
    output = []
    for raw in raw_events:
        event = _event_dict(
            raw,
            source="public_event_entity",
            source_entity=state.entity_id,
        )
        if event is not None:
            output.append(event)
    return output, True


def _coordinator_power_up_events(
    hass: Any, account_hint: str | None
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Read BottlecapDave 19.0.1+ coordinator data as a fail-safe fallback."""
    hass_data = getattr(hass, "data", {})
    domain_data = (
        hass_data.get(_OCTOPUS_DOMAIN) if isinstance(hass_data, Mapping) else None
    )
    if not isinstance(domain_data, Mapping):
        return [], False, None
    candidates = []
    for account_id, account_data in domain_data.items():
        if (
            not isinstance(account_data, Mapping)
            or _COORDINATOR_KEY not in account_data
        ):
            continue
        if account_hint and _normalise_account(account_id) != account_hint:
            continue
        candidates.append((str(account_id), account_data[_COORDINATOR_KEY]))
    if len(candidates) != 1:
        return [], bool(candidates), None
    account_id, coordinator = candidates[0]
    data = getattr(coordinator, "data", None)
    raw_events = getattr(data, "joined_power_up_events", None)
    if not isinstance(raw_events, list):
        return [], True, account_id
    output = []
    for raw in raw_events:
        event = _event_dict(
            raw,
            source="octopus_coordinator",
            source_entity=None,
        )
        if event is not None:
            output.append(event)
    return output, True, account_id


def _eligible(event: dict[str, Any], now: datetime) -> bool:
    """Return whether one Power Up event has the conservative Happy Hour shape."""
    start = event["start"]
    end = event["end"]
    if end < now - _RECENT_GRACE or start > now + _LOOKAHEAD:
        return False
    # Free-electricity feed records carry a code; GraphQL joined Power Up / HH
    # records do not. Never classify coded generic free-electricity events.
    if event.get("code"):
        return False
    local_start = start.astimezone(_LONDON)
    if local_start.weekday() < 5:
        return False
    duration = float(event.get("duration_minutes") or 0.0)
    return 55.0 <= duration <= 125.0


def _merge_consecutive(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge two consecutive one-hour rewards into one two-hour Happy Hour."""
    if not events:
        return []
    ordered = sorted(events, key=lambda item: item["start"])
    groups: list[list[dict[str, Any]]] = []
    for event in ordered:
        if not groups:
            groups.append([event])
            continue
        prior = groups[-1][-1]
        gap = abs((event["start"] - prior["end"]).total_seconds())
        combined_minutes = (
            event["end"] - groups[-1][0]["start"]
        ).total_seconds() / 60.0
        if gap <= _CONTIGUOUS_TOLERANCE_SECONDS and combined_minutes <= 125.0:
            groups[-1].append(event)
        else:
            groups.append([event])

    merged = []
    for group in groups:
        first = group[0]
        last = group[-1]
        merged.append(
            {
                **first,
                "end": last["end"],
                "duration_minutes": (last["end"] - first["start"]).total_seconds()
                / 60.0,
                "event_ids": [
                    item.get("id") for item in group if item.get("id")
                ],
            }
        )
    return merged


def _select_candidate(
    events: list[dict[str, Any]], now: datetime
) -> tuple[dict[str, Any] | None, str]:
    """Select one current/upcoming HH, refusing ambiguous non-contiguous events."""
    eligible = _merge_consecutive([event for event in events if _eligible(event, now)])
    active = [event for event in eligible if event["start"] <= now < event["end"]]
    if len(active) == 1:
        return active[0], "detected_active"
    if len(active) > 1:
        return None, "ambiguous_active_power_up_events"

    upcoming = [event for event in eligible if event["start"] >= now]
    if len(upcoming) == 1:
        return upcoming[0], "detected_upcoming"
    if len(upcoming) > 1:
        return None, "ambiguous_upcoming_power_up_events"

    recent = [event for event in eligible if event["end"] >= now - _RECENT_GRACE]
    if len(recent) == 1:
        return recent[0], "detected_recent_completed"
    if len(recent) > 1:
        return None, "ambiguous_recent_power_up_events"
    return None, "no_confident_weekend_happy_hour"


def automatic_happy_hour_event(
    hass: Any,
    *,
    manual_options: Mapping[str, Any],
    saving_session_entity: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve Octopus automatic Happy Hour first, then the manual fallback."""
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    account_hint = _account_hint_from_entity(saving_session_entity)

    events, public_supported = _public_power_up_events(hass, account_hint)
    source_supported = public_supported
    source_kind = "public_event_entity" if public_supported else None
    source_account = None
    if not events:
        coordinator_events, coordinator_supported, source_account = (
            _coordinator_power_up_events(hass, account_hint)
        )
        source_supported = source_supported or coordinator_supported
        if coordinator_supported:
            events = coordinator_events
            source_kind = "octopus_coordinator"

    candidate, status = _select_candidate(events, now_utc)
    if candidate is not None:
        duration_hours = max(
            (candidate["end"] - candidate["start"]).total_seconds() / 3600.0,
            0.0,
        )
        duration_hours = 2 if duration_hours >= 1.5 else 1
        return {
            "enabled": True,
            "source": "octopus_energy",
            "automatic_source_supported": True,
            "automatic_status": status,
            "source_kind": source_kind,
            "source_entity": candidate.get("source_entity"),
            "source_account": source_account,
            "classification_basis": (
                "code-less weekend Power Up, 1/2-hour conservative match"
            ),
            "confidence": "conservative",
            "event_ids": candidate.get("event_ids")
            or ([candidate.get("id")] if candidate.get("id") else []),
            "start": candidate["start"],
            "end": candidate["end"],
            "duration_hours": duration_hours,
            "fair_use_cap_kwh": (
                HAPPY_HOUR_FAIR_USE_KWH_PER_REWARD * duration_hours
            ),
        }

    manual = dict(manual_happy_hour_event(manual_options))
    manual.update(
        {
            "source": "manual",
            "automatic_source_supported": source_supported,
            "automatic_status": (
                status if source_supported else "power_up_source_unavailable"
            ),
            "source_kind": source_kind,
            "source_account": source_account,
            "fallback_reason": status,
        }
    )
    return manual


_AUTO_DASHBOARD_INSERT = """          This page keeps the operating view deliberately simple. Detailed price-slot, validation and shadow evidence remains available in KEMS diagnostics.

      - type: markdown
        title: Weekend Happy Hour
        content: |
          {% set src = state_attr('sensor.kems_agile_happy_hour_plan', 'source') %}
          {% set auto = state_attr('sensor.kems_agile_happy_hour_plan', 'automatic_status') %}
          **Source:** {{ 'Octopus Energy — automatic' if src == 'octopus_energy' else 'Manual fallback' }}  
          **Plan:** {{ states('sensor.kems_agile_happy_hour_plan') }}  
          **Start:** {{ state_attr('sensor.kems_agile_happy_hour_plan', 'start') or '—' }}  
          **End:** {{ state_attr('sensor.kems_agile_happy_hour_plan', 'end') or '—' }}  
          **Duration:** {{ state_attr('sensor.kems_agile_happy_hour_plan', 'duration_hours') or '—' }} h  
          **Automatic source:** {{ auto or 'waiting for Octopus Power Up data' }}

          {% if src == 'octopus_energy' %}
          Book Weekend Happy Hour in Octopus; KEMS has detected the event automatically. The controls below are fallback only.
          {% else %}
          KEMS could not identify one unambiguous Weekend Happy Hour automatically. Manual controls remain available as a safe fallback.
          {% endif %}

      - type: entities
        title: Happy Hour fallback controls
        show_header_toggle: false
        entities:
          - switch.kems_weekend_happy_hour_planning
          - datetime.kems_weekend_happy_hour_start
          - select.kems_weekend_happy_hour_duration
          - sensor.kems_agile_happy_hour_plan
          - sensor.kems_agile_power_down_priority

      - type: grid
        columns: 4
"""


def install_automatic_happy_hour() -> None:
    """Make Octopus Power Up discovery the preferred Happy Hour source."""
    from . import agile_event_priority_runtime as runtime

    original_event = runtime._happy_hour_event
    if getattr(original_event, "_kems_automatic_happy_hour", False):
        return
    original_context = runtime._happy_hour_context

    def resolved_event(self) -> dict[str, Any]:
        entry_id = getattr(self, "_kems_alpha743_entry_id", None)
        entry = (
            self._hass.config_entries.async_get_entry(str(entry_id))
            if entry_id
            else None
        )
        options = dict(entry.options) if entry is not None else {}
        data = dict(entry.data) if entry is not None else {}
        return automatic_happy_hour_event(
            self._hass,
            manual_options=options,
            saving_session_entity=data.get("saving_session_events"),
        )

    resolved_event._kems_automatic_happy_hour = True
    runtime._happy_hour_event = resolved_event

    def context_with_source(
        self,
        state,
        *,
        now,
        config,
        tariff,
        power_down,
        safe_available_kwh=None,
    ):
        event = resolved_event(self)
        context = original_context(
            self,
            state,
            now=now,
            config=config,
            tariff=tariff,
            power_down=power_down,
            safe_available_kwh=safe_available_kwh,
        )
        for key in (
            "source",
            "automatic_source_supported",
            "automatic_status",
            "source_kind",
            "source_entity",
            "source_account",
            "classification_basis",
            "confidence",
            "event_ids",
            "fallback_reason",
        ):
            if key in event:
                context[key] = event[key]
        return context

    context_with_source._kems_automatic_happy_hour = True
    runtime._happy_hour_context = context_with_source
    runtime._DASHBOARD_INSERT = _AUTO_DASHBOARD_INSERT
