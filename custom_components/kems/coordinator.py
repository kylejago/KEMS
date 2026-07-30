"""Data coordinator for KEMS."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .collector import Collector


class KEMSCoordinator(DataUpdateCoordinator):
    """Coordinate updates from KEMS providers."""

    def __init__(
        self,
        hass: HomeAssistant,
        collector: Collector,
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name="KEMS",
            update_interval=timedelta(minutes=5),
        )

        self._collector = collector

    async def _async_update_data(self):
        """Fetch fresh data from all providers."""
        return self._collector.collect()
