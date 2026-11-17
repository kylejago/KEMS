"""Restart-persistent read-only candidate counter evidence for KEMS.

Uses a delayed Home Assistant Store checkpoint, not live-control writes.
Never approves a meter, fills energy gaps, or books a Happy Hour credit.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .kems_core.counter_evidence import CounterEvidenceSeries

_LOGGER = logging.getLogger(__name__)


class FoxESSCounterEvidenceRecorder:
    """Record bounded fresh cumulative reports across integration restarts."""

    def __init__(self, hass: Any, entry_id: str, import_power_entity: str) -> None:
        self._hass = hass
        self._store = Store(hass, 1, f"kems.{entry_id}.foxess_counter_evidence")
        self._series = CounterEvidenceSeries(import_power_entity)
        self._last_storage_error: str | None = None
        self._restored_samples = 0
        self._checkpoint_requests = 0
        self._observation_checks = 0
        self._accepted_observation_batches = 0
        self._last_observation_checked_at: datetime | None = None

    async def async_load(self) -> None:
        """Never let optional counter evidence block KEMS physical control."""
        try:
            stored = await self._store.async_load() or {}
            self._series.restore(stored, now=dt_util.now())
        except Exception as error:
            self._last_storage_error = str(error)[:256]
            _LOGGER.warning("KEMS optional counter evidence load failed: %s", error)
            return
        self._restored_samples = sum(len(items) for items in self._series.rows.values())

    def observe(self, *, now: datetime) -> None:
        """Observe counter HA states without awaiting I/O or using them in dispatch."""
        self._observation_checks += 1
        self._last_observation_checked_at = now
        if not self._series.observe(self._hass, now=now):
            return
        self._accepted_observation_batches += 1
        try:
            self._store.async_delay_save(self._series.payload, 300)
            self._checkpoint_requests += 1
        except Exception as error:
            # The counter audit never prevents a live physical update.
            self._last_storage_error = str(error)[:256]
            _LOGGER.warning("KEMS optional counter evidence save not queued: %s", error)

    @property
    def status(self) -> dict[str, Any]:
        """Expose audit provenance without suggesting counter approval."""
        return {
            **self._series.status(),
            "restored_samples": self._restored_samples,
            "observation_checks_since_setup": self._observation_checks,
            "accepted_observation_batches_since_setup": (
                self._accepted_observation_batches
            ),
            "last_observation_checked_at": (
                self._last_observation_checked_at.isoformat()
                if self._last_observation_checked_at is not None
                else None
            ),
            "observation_independent_of_sampled_history": True,
            "delayed_checkpoint_requests": self._checkpoint_requests,
            "last_storage_error": self._last_storage_error,
            "storage_schema_version": 1,
            "persistent_across_restarts": True,
        }

    async def async_shutdown(self) -> None:
        """Flush the last observations on clean integration unload."""
        try:
            await self._store.async_save(self._series.payload())
        except Exception as error:
            self._last_storage_error = str(error)[:256]
            _LOGGER.warning("KEMS optional counter evidence flush failed: %s", error)
