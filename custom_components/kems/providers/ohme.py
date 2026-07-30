"""Ohme provider."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from ..kems_core.ohme import OhmeState
from .base import HomeAssistantStateReader
from .entity_map import KEMSEntities


class OhmeProvider(HomeAssistantStateReader):
    """Read data from configured Ohme entities."""

    def __init__(self, hass: HomeAssistant, entities: KEMSEntities) -> None:
        """Initialise the provider."""
        super().__init__(hass)
        self._entities = entities

    def get_state(self) -> OhmeState:
        """Return the current Ohme observation."""
        return OhmeState(
            connected=self._bool(self._entities.ev_connected),
            charging=self._bool(self._entities.ev_charging),
            power_kw=self._float(self._entities.ev_power),
            vehicle_soc=self._float(self._entities.ev_soc),
        )
