"""Shared state-reading helpers for KEMS providers."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

_INVALID_STATES = {STATE_UNKNOWN, STATE_UNAVAILABLE, "none", ""}


class HomeAssistantStateReader:
    """Read and safely convert values from Home Assistant's state machine."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialise the reader."""
        self._hass = hass

    def _state(self, entity_id: str | None) -> State | None:
        """Return an entity state, or None when no entity is configured."""
        if not entity_id:
            return None
        return self._hass.states.get(entity_id)

    def _float(self, entity_id: str | None) -> float | None:
        """Read a numeric state."""
        state = self._state(entity_id)
        if state is None or state.state.lower() in _INVALID_STATES:
            return None

        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _bool(self, entity_id: str | None) -> bool | None:
        """Read an on/off state."""
        state = self._state(entity_id)
        if state is None or state.state.lower() in _INVALID_STATES:
            return None
        if state.state == STATE_ON:
            return True
        if state.state == STATE_OFF:
            return False
        return None

    def _datetime(self, entity_id: str | None) -> datetime | None:
        """Read an ISO 8601 timestamp state."""
        state = self._state(entity_id)
        if state is None or state.state.lower() in _INVALID_STATES:
            return None

        value = dt_util.parse_datetime(state.state)
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def _rate_pence(self, entity_id: str | None) -> float | None:
        """Read an import rate and normalise it to pence per kWh."""
        state = self._state(entity_id)
        if state is None or state.state.lower() in _INVALID_STATES:
            return None

        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None

        unit = str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, ""))
        normalised_unit = unit.casefold().replace(" ", "")
        if normalised_unit in {"gbp/kwh", "£/kwh"}:
            return value * 100
        return value
