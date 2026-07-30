"""Data update coordinator for KEMS."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .collector import Collector
from .const import NAME
from .history import HistoryRecorder
from .kems_core import (
    AdviceEngine,
    KEMSData,
    LearningEngine,
    SimulationEngine,
    assess_quality,
)
from .providers.entity_map import KEMSEntities
from .settings import KEMSSettings

LOGGER = logging.getLogger(__name__)


class KEMSCoordinator(DataUpdateCoordinator[KEMSData]):
    """Coordinate Observe, Learn, Advise, and Simulate stages."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        collector: Collector,
        entities: KEMSEntities,
        settings: KEMSSettings,
    ) -> None:
        """Initialise the coordinator."""
        self.entry = entry
        self.entities = entities
        self.settings = settings
        self._collector = collector
        self._history = HistoryRecorder(
            hass,
            entry.entry_id,
            settings.history_days,
        )
        self._learning = LearningEngine()
        self._advice = AdviceEngine()
        self._simulation = SimulationEngine()

        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=NAME,
            update_interval=timedelta(seconds=settings.scan_interval_seconds),
            always_update=False,
        )

    async def _async_setup(self) -> None:
        """Load retained learning history once before the first refresh."""
        await self._history.async_load()

    async def _async_update_data(self) -> KEMSData:
        """Run the complete read-only KEMS analysis pipeline."""
        try:
            snapshot = self._collector.collect()
            await self._history.async_record(snapshot)
            now = dt_util.now()
            records = self._history.records
            learned = self._learning.analyse(records, now)
            advice = self._advice.evaluate(
                snapshot,
                learned,
                self.settings.simulation,
            )
            simulation = self._simulation.simulate_today(
                records,
                now,
                self.settings.simulation,
            )
            quality = assess_quality(
                snapshot,
                self.entities.configured_snapshot_fields(),
            )
            phase = self._phase(learned.ready, simulation.ready)
            return KEMSData(
                snapshot=snapshot,
                learned=learned,
                advice=advice,
                simulation=simulation,
                quality=quality,
                history_samples=len(records),
                phase=phase,
            )
        except Exception as err:
            raise UpdateFailed(f"KEMS analysis failed: {err}") from err

    async def async_shutdown(self) -> None:
        """Flush learning history before unloading."""
        await self._history.async_save()

    @staticmethod
    def _phase(learning_ready: bool, simulation_ready: bool) -> str:
        """Return the furthest currently active read-only phase."""
        if simulation_ready and learning_ready:
            return "Observe → Learn → Advise → Simulate"
        if learning_ready:
            return "Observe → Learn → Advise"
        return "Observe → Learn"
