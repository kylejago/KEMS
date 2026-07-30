"""Octopus Energy state provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.core import HomeAssistant

from .base import HomeAssistantStateReader
from .entity_map import KEMSEntities


@dataclass(frozen=True, slots=True)
class OctopusState:
    """Current Octopus tariff observation."""

    current_import_rate: float | None = None
    next_import_rate: float | None = None
    current_export_rate: float | None = None
    off_peak: bool | None = None
    intelligent_slot: bool | None = None
    next_offpeak_start: datetime | None = None
    offpeak_end: datetime | None = None


class OctopusProvider(HomeAssistantStateReader):
    """Read data from configured Octopus Energy entities."""

    def __init__(self, hass: HomeAssistant, entities: KEMSEntities) -> None:
        """Initialise the provider."""
        super().__init__(hass)
        self._entities = entities

    def get_state(self) -> OctopusState:
        """Return the current Octopus observation."""
        return OctopusState(
            current_import_rate=self._rate_pence(self._entities.current_import_rate),
            next_import_rate=self._rate_pence(self._entities.next_import_rate),
            current_export_rate=self._rate_pence(self._entities.current_export_rate),
            off_peak=self._bool(self._entities.off_peak),
            intelligent_slot=self._bool(self._entities.intelligent_slot),
            next_offpeak_start=self._datetime(self._entities.next_offpeak_start),
            offpeak_end=self._datetime(self._entities.offpeak_end),
        )
