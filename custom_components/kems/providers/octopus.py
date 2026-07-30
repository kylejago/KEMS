"""Octopus Energy provider."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import HomeAssistant

from kems_core.octopus import OctopusState

from .entity_map import OctopusEntities


class OctopusProvider:
    """Reads data from the Octopus integrations."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._entities = OctopusEntities()

    def _state(self, entity_id: str):
        """Return a Home Assistant State object."""
        return self._hass.states.get(entity_id)

    def _float(self, entity_id: str) -> float | None:
        state = self._state(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None

        try:
            return float(state.state)
        except ValueError:
            return None

    def _bool(self, entity_id: str) -> bool:
        state = self._state(entity_id)
        return state is not None and state.state == "on"

    def _datetime(self, entity_id: str) -> datetime | None:
        state = self._state(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None

        try:
            return datetime.fromisoformat(state.state)
        except ValueError:
            return None

    def get_state(self) -> OctopusState:
        """Return the current Octopus state."""

        return OctopusState(
            current_rate=self._float(self._entities.current_rate),
            next_rate=self._float(self._entities.next_rate),
            off_peak=self._bool(self._entities.off_peak),
            intelligent_slot=self._bool(self._entities.intelligent_slot),
            planned_dispatch=self._bool(self._entities.planned_dispatch),
            next_offpeak_start=self._datetime(self._entities.next_offpeak_start),
            offpeak_end=self._datetime(self._entities.offpeak_end),
        )
