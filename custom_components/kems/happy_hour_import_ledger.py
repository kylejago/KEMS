"""Restart-safe physical grid import observations for booked reward hours.

This recorder is read-only. It never grants an Octopus booking or tariff
authority: the independent Happy Hour controller continues to do that.
Every usable physical meter sample is persisted during a confirmed reward
window (including the preceding ten minutes), avoiding the much slower
five-minute KEMS financial-history checkpoint after a Home Assistant restart.
Unknown meter intervals still fail the strict reward ledger coverage gate.
Completed hours are retained long enough for the following morning's guarded
maintenance restart to recover stored proof and seal a per-hour financial receipt.
Retention NEVER authorises live charge, export or a future Octopus booking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_NAMESPACE

_STORAGE_VERSION = 1
_PRE_EVENT_SEED = timedelta(minutes=10)
# Archive physical proof for the next safe maintenance window and delayed
# HA restarts. Previously six hours meant complete reward hours vanished from
# in-memory financial evidence *before* the next morning, although the last
# physically persisted file still contained the original samples.
_RETENTION = timedelta(days=7)
_MAX_SAMPLES = 1500
_MAX_METER_AGE_SECONDS = 30.0
_MAX_SNAPSHOT_CLOCK_SKEW_SECONDS = 60.0


def _utc(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(UTC)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


@dataclass(frozen=True)
class GridImportReading:
    """A witnessed physical site-import power measurement."""

    timestamp: datetime
    grid_import_kw: float


class HappyHourImportLedgerRecorder:
    """Persist a short physical grid-import timeline across KEMS restarts."""

    def __init__(self, hass: Any, entry_id: str, *, grid_import_entity: str | None):
        self._grid_import_entity = str(grid_import_entity or "")
        self._store = Store(
            hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}.{STORAGE_NAMESPACE}.happy_hour_import_ledger",
        )
        self._samples: list[GridImportReading] = []
        self._windows: list[tuple[datetime, datetime]] = []
        self._load_status = "not_loaded"
        self._last_saved_at: datetime | None = None

    @property
    def samples(self) -> list[GridImportReading]:
        return list(self._samples)

    @property
    def status(self) -> dict[str, Any]:
        return {
            "source_entity": self._grid_import_entity,
            "load_status": self._load_status,
            "retention_days": _RETENTION.days,
            "last_saved_sample": self._last_saved_at.isoformat() if self._last_saved_at else None,
            "retained_samples": len(self._samples),
            "first_sample": (
                self._samples[0].timestamp.isoformat() if self._samples else None
            ),
            "last_sample": (
                self._samples[-1].timestamp.isoformat() if self._samples else None
            ),
            "persisted_reward_windows": [
                {"start": start.isoformat(), "end": end.isoformat()}
                for start, end in self._windows
            ],
            "policy": "physical readings only; missing coverage fails closed",
        }

    def _prune(self, now: datetime) -> None:
        cutoff = now - _RETENTION
        self._samples = [
            sample
            for sample in self._samples
            if cutoff <= sample.timestamp <= now + timedelta(minutes=1)
        ][-_MAX_SAMPLES:]
        self._windows = [
            (start, end)
            for start, end in self._windows
            if end >= cutoff and start <= now + timedelta(days=7)
        ]

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        if not data:
            self._load_status = "no_saved_evidence"
            return
        if data.get("source_entity") != self._grid_import_entity:
            self._load_status = "different_meter_source"
            # A changed/rebound physical source cannot reuse an earlier
            # meter's reward allowance after a restart.
            self._samples = []
            self._windows = []
            return
        now = datetime.now(UTC)
        recovered: dict[datetime, GridImportReading] = {}
        for item in data.get("samples", []):
            if not isinstance(item, dict):
                continue
            at = _utc(item.get("timestamp"))
            power = _number(item.get("grid_import_kw"))
            if at is not None and power is not None and power >= 0.0:
                recovered[at] = GridImportReading(at, power)
        self._samples = [recovered[at] for at in sorted(recovered)]
        self._last_saved_at = self._samples[-1].timestamp if self._samples else None
        self._load_status = "restored" if self._samples else "empty_saved_store"
        self._windows = []
        for item in data.get("windows", []):
            if not isinstance(item, dict):
                continue
            start = _utc(item.get("start"))
            end = _utc(item.get("end"))
            if start is not None and end is not None and start < end:
                self._windows.append((start, end))
        self._prune(now)

    async def async_observe(
        self,
        snapshot: Any,
        *,
        now: datetime,
        confirmed_windows: list[dict[str, Any]],
    ) -> bool:
        """Persist each fresh scan near a confirmed reward period.

        A write failure prevents using the new sample for live authority;
        a later scan may try again. Saving is intentionally per control scan
        so a normal Home Assistant restart does not lose 15 minutes of meter
        readings as the financial history would.
        """
        now_utc = now.astimezone(UTC)
        for item in confirmed_windows:
            start = _utc(item.get("start"))
            end = _utc(item.get("end"))
            if start is not None and end is not None and start < end:
                window = (start, end)
                if window not in self._windows:
                    self._windows.append(window)
        self._prune(now_utc)
        if not any(
            start - _PRE_EVENT_SEED <= now_utc < end for start, end in self._windows
        ):
            return False

        timestamp = _utc(getattr(snapshot, "timestamp", None))
        power = _number(getattr(snapshot, "grid_import_kw", None))
        ages = getattr(snapshot, "source_age_seconds", None)
        source_age = _number(
            ages.get("grid_import_kw") if isinstance(ages, dict) else None
        )
        if (
            not self._grid_import_entity
            or timestamp is None
            or abs((now_utc - timestamp).total_seconds())
            > _MAX_SNAPSHOT_CLOCK_SKEW_SECONDS
            or power is None
            or power < 0.0
            or source_age is None
            or not 0.0 <= source_age <= _MAX_METER_AGE_SECONDS
            or "grid_import_kw" in (getattr(snapshot, "stale_fields", ()) or ())
            or (self._samples and timestamp <= self._samples[-1].timestamp)
        ):
            return False

        self._samples.append(GridImportReading(timestamp, power))
        self._prune(now_utc)
        try:
            await self._store.async_save(
                {
                    "source_entity": self._grid_import_entity,
                    "windows": [
                        {"start": start.isoformat(), "end": end.isoformat()}
                        for start, end in self._windows
                    ],
                    "samples": [
                        {
                            "timestamp": sample.timestamp.isoformat(),
                            "grid_import_kw": sample.grid_import_kw,
                        }
                        for sample in self._samples
                    ],
                }
            )
        except Exception:
            # A sample that failed persistence cannot prove continuity
            # after a subsequent restart. Keep the last durable timeline.
            self._samples.pop()
            return False
        self._load_status = "recording"
        self._last_saved_at = timestamp
        return True
