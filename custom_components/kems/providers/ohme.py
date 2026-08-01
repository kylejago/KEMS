"""Ohme state provider."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from ..kems_core import interpret_charger_status
from .base import HomeAssistantStateReader
from .entity_map import KEMSEntities


@dataclass(frozen=True, slots=True)
class OhmeState:
    """Current Ohme observation."""

    status: str | None = None
    connected: bool | None = None
    charging: bool | None = None
    power_kw: float | None = None
    vehicle_soc: float | None = None


class OhmeProvider(HomeAssistantStateReader):
    """Read data from configured Ohme entities."""

    def __init__(self, hass: HomeAssistant, entities: KEMSEntities) -> None:
        """Initialise the provider."""
        super().__init__(hass)
        self._entities = entities

    def get_state(self) -> OhmeState:
        """Return the current Ohme observation."""
        status = self._text(self._entities.ev_status)
        power_kw = self._power_kw(self._entities.ev_power_kw)
        status_connected, status_charging = interpret_charger_status(status)

        if status is not None:
            connected = status_connected
            charging = status_charging
        else:
            connected = self._bool(self._entities.ev_connected)
            charging = self._bool(self._entities.ev_charging)

        if power_kw is not None and power_kw > 0.1:
            connected = True
            charging = True

        return OhmeState(
            status=status,
            connected=connected,
            charging=charging,
            power_kw=power_kw,
            vehicle_soc=self._float(self._entities.ev_soc),
        )
