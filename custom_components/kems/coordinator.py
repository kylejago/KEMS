"""Data coordinator for KEMS."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from kems_core.snapshot import Snapshot

from .collector import Collector

LOGGER = logging.getLogger(__name__)


class KEMSCoordinator(DataUpdateCoordinator[Snapshot]):
    """Coordinates updates for KEMS."""

    def __init__(
        self,
        hass: HomeAssistant,
        collector: Collector,
    ) -> None:
        """Initialise the coordinator."""

        self._collector = collector

        super().__init__(
            hass,
            logger=LOGGER,
            name="KEMS",
            update_interval=timedelta(minutes=5),
        )

    async def _async_update_data(self) -> Snapshot:
        """Fetch the latest snapshot."""

        return self._collector.collect()
