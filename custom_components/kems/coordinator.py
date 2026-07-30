"""Data update coordinator for KEMS."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .collector import Collector
from .const import DEFAULT_SCAN_INTERVAL_SECONDS, NAME
from .kems_core.snapshot import Snapshot

LOGGER = logging.getLogger(__name__)


class KEMSCoordinator(DataUpdateCoordinator[Snapshot]):
    """Coordinate KEMS observations for all entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        collector: Collector,
    ) -> None:
        """Initialise the coordinator."""
        self.entry = entry
        self._collector = collector

        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=NAME,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
        )

    async def _async_update_data(self) -> Snapshot:
        """Read the latest state-machine snapshot."""
        return self._collector.collect()
