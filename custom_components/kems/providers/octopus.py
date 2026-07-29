"""Octopus Energy provider."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from kems_core.octopus import OctopusState


class OctopusProvider:
    """Reads data from the Octopus integrations."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def get_state(self) -> OctopusState:
        """Return the current Octopus state."""

        return OctopusState()
