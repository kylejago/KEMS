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

    def _report_age_seconds(
        self,
        entity_id: str | None,
        now: datetime | None = None,
    ) -> float | None:
        """Return seconds since Home Assistant last received this source."""
        state = self._state(entity_id)
        if state is None:
            return None
        reported = getattr(state, "last_reported", None) or state.last_updated
        if reported.tzinfo is None:
            reported = reported.replace(tzinfo=UTC)
        reference = now or dt_util.now()
        return max((reference - reported).total_seconds(), 0.0)

    def _source_is_fresh(
        self,
        entity_id: str | None,
        max_age_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        """Return whether a configured source has reported recently enough."""
        age = self._report_age_seconds(entity_id, now)
        return age is not None and age <= max(max_age_seconds, 30)

    def _fresh_float(
        self,
        entity_id: str | None,
        max_age_seconds: int,
        now: datetime | None = None,
    ) -> float | None:
        """Read a number only when the source has reported recently."""
        if not self._source_is_fresh(entity_id, max_age_seconds, now):
            return None
        return self._float(entity_id)

    def _fresh_power_kw(
        self,
        entity_id: str | None,
        max_age_seconds: int,
        now: datetime | None = None,
    ) -> float | None:
        """Read power only when the source has reported recently."""
        if not self._source_is_fresh(entity_id, max_age_seconds, now):
            return None
        return self._power_kw(entity_id)

    def _text(self, entity_id: str | None) -> str | None:
        """Read a non-empty text state."""
        state = self._state(entity_id)
        if state is None or state.state.casefold() in _INVALID_STATES:
            return None
        return state.state

    def _float(self, entity_id: str | None) -> float | None:
        """Read a numeric state."""
        state = self._state(entity_id)
        if state is None or state.state.casefold() in _INVALID_STATES:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _power_kw(self, entity_id: str | None) -> float | None:
        """Read power and normalise it to kW."""
        state = self._state(entity_id)
        value = self._numeric_state(state)
        if value is None:
            return None
        unit = self._unit(state)
        if unit in {"w", "watt", "watts"}:
            return value / 1000
        return value

    def _energy_kwh(
        self,
        entity_id: str | None,
        gas_kwh_per_m3: float = 11.1868,
    ) -> float | None:
        """Read energy or gas volume and normalise it to kWh."""
        state = self._state(entity_id)
        value = self._numeric_state(state)
        if value is None:
            return None
        unit = self._unit(state)
        if unit in {"wh", "watt hour", "watt hours"}:
            return value / 1000
        if unit in {"m3", "m³", "cubic metre", "cubic metres"}:
            return value * gas_kwh_per_m3
        return value

    def _money_pence(self, entity_id: str | None) -> float | None:
        """Read currency and normalise it to pence."""
        state = self._state(entity_id)
        value = self._numeric_state(state)
        if value is None:
            return None
        unit = self._unit(state)
        if (
            unit.startswith("gbp")
            or unit.startswith("£")
            or unit in {"pounds", "pound"}
        ):
            return value * 100
        return value

    def _bool(self, entity_id: str | None) -> bool | None:
        """Read an on/off state."""
        state = self._state(entity_id)
        if state is None or state.state.casefold() in _INVALID_STATES:
            return None
        if state.state == STATE_ON:
            return True
        if state.state == STATE_OFF:
            return False
        return None

    def _datetime(self, entity_id: str | None) -> datetime | None:
        """Read an ISO 8601 timestamp state."""
        state = self._state(entity_id)
        if state is None or state.state.casefold() in _INVALID_STATES:
            return None
        value = dt_util.parse_datetime(state.state)
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def _rate_pence(self, entity_id: str | None) -> float | None:
        """Read an energy rate and normalise it to pence per kWh."""
        state = self._state(entity_id)
        value = self._numeric_state(state)
        if value is None:
            return None
        unit = self._unit(state).replace(" ", "")
        if unit in {"gbp/kwh", "£/kwh"}:
            return value * 100
        return value

    @staticmethod
    def _numeric_state(state: State | None) -> float | None:
        """Return a state's numeric value."""
        if state is None or state.state.casefold() in _INVALID_STATES:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _unit(state: State | None) -> str:
        """Return a normalised unit string."""
        if state is None:
            return ""
        return str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")).casefold()
