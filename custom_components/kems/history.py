"""Persistent rolling observation history for KEMS."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DEFAULT_RECORD_INTERVAL_SECONDS, DOMAIN
from .kems_core import Snapshot

STORAGE_VERSION = 1
SAVE_EVERY_RECORDS = 3


class HistoryRecorder:
    """Retain compact read-only observations in Home Assistant storage."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        history_days: int,
    ) -> None:
        """Initialise the history recorder."""
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.history",
        )
        self._history_days = max(history_days, 1)
        self._records: list[Snapshot] = []
        self._unsaved_records = 0

    @property
    def records(self) -> list[Snapshot]:
        """Return retained records in chronological order."""
        return list(self._records)

    async def async_load(self) -> None:
        """Load stored observations and discard expired records."""
        data = await self._store.async_load()
        if not data:
            self._records = []
            return

        records: list[Snapshot] = []
        for item in data.get("records", []):
            try:
                records.append(Snapshot.from_dict(item))
            except (TypeError, ValueError):
                continue
        self._records = sorted(records, key=lambda record: record.timestamp)
        self._prune()

    async def async_record(self, snapshot: Snapshot) -> bool:
        """Record a snapshot when the sampling interval has elapsed."""
        if self._records:
            elapsed = snapshot.timestamp - self._records[-1].timestamp
            if elapsed < timedelta(seconds=DEFAULT_RECORD_INTERVAL_SECONDS):
                return False

        self._records.append(snapshot)
        self._prune()
        self._unsaved_records += 1
        if self._unsaved_records >= SAVE_EVERY_RECORDS:
            await self.async_save()
        return True

    async def async_save(self) -> None:
        """Persist retained observations."""
        await self._store.async_save(
            {"records": [record.to_dict() for record in self._records]}
        )
        self._unsaved_records = 0

    def _prune(self) -> None:
        """Discard observations outside the configured history window."""
        if not self._records:
            return
        cutoff = self._records[-1].timestamp - timedelta(days=self._history_days)
        self._records = [
            record for record in self._records if record.timestamp >= cutoff
        ]
