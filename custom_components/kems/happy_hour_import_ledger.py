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
_POST_EVENT_EVIDENCE_GRACE = timedelta(minutes=10)
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
    import_rate_pence: float | None = None


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
        self._confirmation_sources: dict[tuple[datetime, datetime], dict[str, Any]] = {}
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
            "last_saved_sample": (
                self._last_saved_at.isoformat() if self._last_saved_at else None
            ),
            "retained_samples": len(self._samples),
            "first_sample": (
                self._samples[0].timestamp.isoformat() if self._samples else None
            ),
            "last_sample": (
                self._samples[-1].timestamp.isoformat() if self._samples else None
            ),
            "persisted_reward_windows": [
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    **self._confirmation_sources.get((start, end), {}),
                }
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
        self._confirmation_sources = {
            window: details
            for window, details in self._confirmation_sources.items()
            if window in self._windows
        }

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
            self._confirmation_sources = {}
            return
        now = datetime.now(UTC)
        recovered: dict[datetime, GridImportReading] = {}
        for item in data.get("samples", []):
            if not isinstance(item, dict):
                continue
            at = _utc(item.get("timestamp"))
            power = _number(item.get("grid_import_kw"))
            if at is not None and power is not None and power >= 0.0:
                rate = _number(item.get("import_rate_pence"))
                recovered[at] = GridImportReading(
                    at, power, rate if rate is not None and 0 <= rate <= 200 else None
                )
        self._samples = [recovered[at] for at in sorted(recovered)]
        self._last_saved_at = self._samples[-1].timestamp if self._samples else None
        self._load_status = "restored" if self._samples else "empty_saved_store"
        self._windows = []
        self._confirmation_sources = {}
        for item in data.get("windows", []):
            if not isinstance(item, dict):
                continue
            start = _utc(item.get("start"))
            end = _utc(item.get("end"))
            if start is not None and end is not None and start < end:
                window = (start, end)
                if window not in self._windows:
                    self._windows.append(window)
                # Legacy two-hour merged windows may remain for diagnostics,
                # but they never become an independently verified reward.
                if 55 <= (end - start).total_seconds() / 60 <= 65:
                    details = {
                        key: item[key]
                        for key in (
                            "event_id",
                            "event_code",
                            "booking_source",
                            "source_entity",
                        )
                        if item.get(key)
                    }
                    if details:
                        self._confirmation_sources[window] = details
        self._prune(now)

    async def async_observe(
        self,
        snapshot: Any,
        *,
        now: datetime,
        confirmed_windows: list[dict[str, Any]],
    ) -> bool:
        """Durably save individual booking proof even if the meter is stale.

        The joined-event feed can expire before the next fresh grid reading.
        A confirmed one-hour receipt is independent of a physical meter sample:
        save its provenance immediately, and separately fail closed on missing
        meter continuity. Neither action authorises live Happy Hour dispatch.
        """
        now_utc = now.astimezone(UTC)
        old_windows = list(self._windows)
        old_sources = dict(self._confirmation_sources)
        old_samples = list(self._samples)
        newly_confirmed = False
        for item in confirmed_windows:
            if not isinstance(item, dict):
                continue
            start = _utc(item.get("start"))
            end = _utc(item.get("end"))
            if (
                start is None
                or end is None
                or not 55 <= (end - start).total_seconds() / 60 <= 65
                or not (
                    item.get("event_code")
                    or item.get("event_id")
                    or item.get("booking_source") == "octopus_joined_events"
                )
            ):
                # Never turn an aggregate 12:00–14:00 session (or a bare
                # advertised event) into two fictional booked allowances.
                continue
            window = (start, end)
            if window in self._windows:
                continue
            self._windows.append(window)
            self._confirmation_sources[window] = {
                key: str(item[key])
                for key in (
                    "event_id",
                    "event_code",
                    "booking_source",
                    "source_entity",
                )
                if item.get(key)
            }
            newly_confirmed = True
        self._prune(now_utc)
        within_window = any(
            start - _PRE_EVENT_SEED <= now_utc < end + _POST_EVENT_EVIDENCE_GRACE
            for start, end in self._windows
        )
        if not within_window and not newly_confirmed:
            return False

        timestamp = _utc(getattr(snapshot, "timestamp", None))
        power = _number(getattr(snapshot, "grid_import_kw", None))
        ages = getattr(snapshot, "source_age_seconds", None)
        source_age = _number(
            ages.get("grid_import_kw") if isinstance(ages, dict) else None
        )
        sample_valid = bool(
            within_window
            and self._grid_import_entity
            and timestamp is not None
            and abs((now_utc - timestamp).total_seconds())
            <= _MAX_SNAPSHOT_CLOCK_SKEW_SECONDS
            and power is not None
            and power >= 0.0
            and source_age is not None
            and 0.0 <= source_age <= _MAX_METER_AGE_SECONDS
            and "grid_import_kw" not in (getattr(snapshot, "stale_fields", ()) or ())
            and (not self._samples or timestamp > self._samples[-1].timestamp)
        )
        if sample_valid:
            # Retain the tariff that accompanied this physical observation.
            # Historical samples without a rate retain None, not today's rate.
            import_rate = _number(getattr(snapshot, "current_import_rate", None))
            rate_fresh = "current_import_rate" not in (
                getattr(snapshot, "tariff_stale_fields", ()) or ()
            )
            observed_rate = (
                import_rate
                if rate_fresh and import_rate is not None and 0 <= import_rate <= 200
                else None
            )
            self._samples.append(GridImportReading(timestamp, power, observed_rate))
            self._prune(now_utc)
        if not newly_confirmed and not sample_valid:
            return False

        try:
            await self._store.async_save(
                {
                    "source_entity": self._grid_import_entity,
                    "windows": [
                        {
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                            **self._confirmation_sources.get((start, end), {}),
                        }
                        for start, end in self._windows
                    ],
                    "samples": [
                        {
                            "timestamp": sample.timestamp.isoformat(),
                            "grid_import_kw": sample.grid_import_kw,
                            "import_rate_pence": sample.import_rate_pence,
                        }
                        for sample in self._samples
                    ],
                }
            )
        except Exception:
            # Failed durable proof must never be presented as persisted.
            self._windows = old_windows
            self._confirmation_sources = old_sources
            self._samples = old_samples
            return False
        if sample_valid:
            self._load_status = "recording"
            self._last_saved_at = timestamp
        elif newly_confirmed:
            self._load_status = "confirmed_windows"
        return sample_valid
