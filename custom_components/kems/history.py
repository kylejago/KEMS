"""Persistent rolling observation history for KEMS.

Alpha9.155 retains the five-minute cadence, three-record checkpoint and
version-one Store schema. Restored/previously encoded observations are reused
without recursing through the whole history every save; only new observations
are encoded in the executor. Normal unload awaits and flushes the final tail.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
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
        # Parallel JSON-ready objects: only newly appended observations are None.
        # Historical records are observations; never mutate them after capture.
        self._encoded_records: list[dict[str, Any] | None] = []
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
        self._last_reused_records = 0
        self._last_encoded_records = 0
        self._last_checkpoint_started_at: str | None = None
        self._last_checkpoint_finished_at: str | None = None

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
            "last_checkpoint_started_at": self._last_checkpoint_started_at,
            "last_checkpoint_finished_at": self._last_checkpoint_finished_at,
            "last_reused_encoded_records": self._last_reused_records,
            "last_newly_encoded_records": self._last_encoded_records,
            "encoded_cache_records": sum(
                item is not None for item in self._encoded_records
            ),
            "live_control_waits_for_checkpoint": False,
            "shutdown_flushes_pending_checkpoint": True,
            "storage_schema_version": STORAGE_VERSION,
        }

    async def async_load(self) -> None:
        """Load stored observations and discard expired records."""
        data = await self._store.async_load()
        if not data:
            self._records = []
            self._encoded_records = []
            return

        pairs: list[tuple[Snapshot, dict[str, Any]]] = []
        for item in data.get("records", []):
            try:
                if not isinstance(item, dict):
                    continue
                pairs.append((Snapshot.from_dict(item), item))
            except (TypeError, ValueError):
                continue
        pairs.sort(key=lambda pair: pair[0].timestamp)
        self._records = [record for record, _ in pairs]
        self._encoded_records = [encoded for _, encoded in pairs]
        self._prune()

    async def async_record(self, snapshot: Snapshot) -> bool:
        """Record in memory; schedule checkpoints without awaiting disk writes."""
        if self._records:
            elapsed = snapshot.timestamp - self._records[-1].timestamp
            if elapsed < timedelta(seconds=DEFAULT_RECORD_INTERVAL_SECONDS):
                return False

        self._records.append(snapshot)
        self._encoded_records.append(None)
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
        cached: list[dict[str, Any] | None],
    ) -> tuple[dict[str, Any], float, dict[int, dict[str, Any]], int]:
        """Encode only new observations; reuse detached JSON-ready history."""
        started = perf_counter()
        encoded: list[dict[str, Any]] = []
        new: dict[int, dict[str, Any]] = {}
        reused = 0
        for record, previous in zip(records, cached, strict=True):
            if previous is None:
                item = record.to_dict()
                new[id(record)] = item
            else:
                item = previous
                reused += 1
            encoded.append(item)
        return {"records": encoded}, round(perf_counter() - started, 3), new, reused

    async def _write_checkpoint(self) -> None:
        """Persist one coherent revision; never acknowledge failed writes."""
        revision = self._record_revision
        started = perf_counter()
        self._last_checkpoint_started_at = datetime.now(UTC).isoformat()
        records = list(self._records)
        cached = list(self._encoded_records)
        try:
            (
                payload,
                self._last_serialize_seconds,
                newly_encoded,
                self._last_reused_records,
            ) = await self._hass.async_add_executor_job(
                self._encode_records, records, cached
            )
            self._last_encoded_records = len(newly_encoded)
            # The coordinator may append/prune during executor encoding.
            # Merge by object identity only for the exact captured records.
            # Newly appended observations remain None until the next save.
            if newly_encoded:
                for index, record in enumerate(self._records):
                    if self._encoded_records[index] is None:
                        item = newly_encoded.get(id(record))
                        if item is not None:
                            self._encoded_records[index] = item
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
            self._last_checkpoint_finished_at = datetime.now(UTC).isoformat()

    async def _async_checkpoint_batch(self) -> None:
        """Coalesce any snapshots arriving while a checkpoint is in flight."""
        while self._record_revision - self._saved_revision >= SAVE_EVERY_RECORDS:
            await self._write_checkpoint()

    async def async_save(self) -> None:
        """Flush in-flight and remaining history on clean integration unload."""
        pending = self._save_task
        if pending is not None:
            # The failed background checkpoint is already logged. Retry the
            # full retained state synchronously during clean unload.
            with suppress(Exception):
                await pending
        if self._record_revision > self._saved_revision:
            await self._write_checkpoint()

    def _prune(self) -> None:
        """Discard observations outside the configured history window."""
        if not self._records:
            return
        cutoff = self._records[-1].timestamp - timedelta(days=self._history_days)
        expired = 0
        for record in self._records:
            if record.timestamp >= cutoff:
                break
            expired += 1
        if expired:
            del self._records[:expired]
            del self._encoded_records[:expired]
