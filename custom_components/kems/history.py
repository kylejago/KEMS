"""Persistent rolling observation history for KEMS.

Alpha9.154 keeps the 5-minute observation cadence and every-third-record
checkpoint, but never makes an ordinary inverter-control scan wait for the
multi-second Home Assistant storage write. Only one checkpoint may run at a
time; a clean integration unload awaits it and flushes the final tail.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from time import perf_counter
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DEFAULT_RECORD_INTERVAL_SECONDS, DOMAIN, STORAGE_NAMESPACE
from .kems_core import Snapshot

STORAGE_VERSION = 1
SAVE_EVERY_RECORDS = 3
_LOGGER = logging.getLogger(__name__)


class HistoryRecorder:
    """Retain compact read-only observations in Home Assistant storage."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        history_days: int,
    ) -> None:
        """Initialise the history recorder."""
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.history",
        )
        self._history_days = max(history_days, 1)
        self._records: list[Snapshot] = []
        self._unsaved_records = 0
        self._record_revision = 0
        self._saved_revision = 0
        self._save_task: asyncio.Task[None] | None = None
        self._checkpoint_count = 0
        self._checkpoint_failures = 0
        self._last_error: str | None = None
        self._last_serialize_seconds = 0.0
        self._last_store_seconds = 0.0
        self._last_total_seconds = 0.0

    @property
    def records(self) -> list[Snapshot]:
        """Return retained records in chronological order."""
        return list(self._records)

    @property
    def status(self) -> dict[str, Any]:
        """Report bounded, read-only persistence timing and recovery evidence."""
        task = self._save_task
        return {
            "samples": len(self._records),
            "save_every_records": SAVE_EVERY_RECORDS,
            "pending_records": self._unsaved_records,
            "checkpoint_in_flight": task is not None and not task.done(),
            "checkpoint_count": self._checkpoint_count,
            "checkpoint_failures": self._checkpoint_failures,
            "last_error": self._last_error,
            "last_serialize_worker_seconds": self._last_serialize_seconds,
            "last_store_await_seconds": self._last_store_seconds,
            "last_checkpoint_total_seconds": self._last_total_seconds,
            "live_control_waits_for_checkpoint": False,
            "shutdown_flushes_pending_checkpoint": True,
            "storage_schema_version": STORAGE_VERSION,
        }

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
        """Record in memory; schedule checkpoints without awaiting disk writes."""
        if self._records:
            elapsed = snapshot.timestamp - self._records[-1].timestamp
            if elapsed < timedelta(seconds=DEFAULT_RECORD_INTERVAL_SECONDS):
                return False

        self._records.append(snapshot)
        self._prune()
        self._record_revision += 1
        self._unsaved_records = self._record_revision - self._saved_revision
        if self._unsaved_records >= SAVE_EVERY_RECORDS:
            self._schedule_checkpoint()
        return True

    def _schedule_checkpoint(self) -> None:
        """Schedule one coalescing HA-owned background task, never one per scan."""
        if self._save_task is not None and not self._save_task.done():
            return
        task = self._hass.async_create_task(self._async_checkpoint_batch())
        self._save_task = task
        task.add_done_callback(self._checkpoint_finished)

    def _checkpoint_finished(self, task: asyncio.Task[None]) -> None:
        """Consume exceptions so HA logs a failure without losing live control."""
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            _LOGGER.error(
                "KEMS history background checkpoint failed; pending records "
                "remain in memory for retry/shutdown",
                exc_info=(type(error), error, error.__traceback__),
            )

    @staticmethod
    def _encode_records(
        records: list[Snapshot],
    ) -> tuple[dict[str, Any], float]:
        """Serialise detached observation references in an HA executor worker."""
        started = perf_counter()
        payload = {"records": [record.to_dict() for record in records]}
        return payload, round(perf_counter() - started, 3)

    async def _write_checkpoint(self) -> None:
        """Persist one coherent revision; never acknowledge failed writes."""
        revision = self._record_revision
        started = perf_counter()
        try:
            payload, self._last_serialize_seconds = await self._hass.async_add_executor_job(
                self._encode_records, list(self._records)
            )
            stored_at = perf_counter()
            await self._store.async_save(payload)
            self._last_store_seconds = round(perf_counter() - stored_at, 3)
        except Exception as error:
            self._checkpoint_failures += 1
            self._last_error = str(error)[:256]
            raise
        else:
            self._saved_revision = revision
            self._unsaved_records = self._record_revision - self._saved_revision
            self._checkpoint_count += 1
            self._last_error = None
        finally:
            self._last_total_seconds = round(perf_counter() - started, 3)

    async def _async_checkpoint_batch(self) -> None:
        """Coalesce any snapshots arriving while a checkpoint is in flight."""
        while self._record_revision - self._saved_revision >= SAVE_EVERY_RECORDS:
            await self._write_checkpoint()

    async def async_save(self) -> None:
        """Flush in-flight and remaining history on clean integration unload."""
        pending = self._save_task
        if pending is not None:
            try:
                await pending
            except Exception:
                # The failed background checkpoint is already logged. Retry the
                # full retained state synchronously during clean unload.
                pass
        if self._record_revision > self._saved_revision:
            await self._write_checkpoint()

    def _prune(self) -> None:
        """Discard observations outside the configured history window."""
        if not self._records:
            return
        cutoff = self._records[-1].timestamp - timedelta(days=self._history_days)
        self._records = [
            record for record in self._records if record.timestamp >= cutoff
        ]
