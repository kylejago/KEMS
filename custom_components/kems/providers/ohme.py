"""Ohme provider."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from ..kems_core.ohme import OhmeState


class OhmeProvider:
    """Read data from Ohme."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def get_state(self) -> OhmeState:
        """Return charger state."""

        return OhmeState()
