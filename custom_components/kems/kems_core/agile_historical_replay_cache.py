"""Bounded exact-input reuse for settled Agile historical comparison days.

Live/current-day and tomorrow projections never use this cache. It changes
no prices, export dispatch, physical energy authority, or hardware writes.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import fields, is_dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from pickle import HIGHEST_PROTOCOL, PicklingError, dumps, loads
from struct import pack
from time import perf_counter
from typing import Any


def exact_snapshot_values_equal(previous: Any, current: Any) -> bool:
    """Return True only for recursively identical supported replay values."""
    if type(previous) is not type(current):
        return False
    if isinstance(previous, float):
        # Float equality ignores -0.0 vs +0.0 and can treat an identical
        # NaN object's payload as equal in tuple/list comparisons.
        return pack("!d", previous) == pack("!d", current)
    if isinstance(previous, datetime):
        # Python datetime equality ignores the fold bit for two London times.
        return (
            previous.isoformat() == current.isoformat()
            and previous.fold == current.fold
            and str(previous.tzinfo) == str(current.tzinfo)
        )
    if isinstance(previous, time):
        return (
            previous.isoformat() == current.isoformat()
            and previous.fold == current.fold
            and str(previous.tzinfo) == str(current.tzinfo)
        )
    if isinstance(previous, (str, int, bool, bytes, type(None), date, timedelta)):
        return previous == current
    if isinstance(previous, (list, tuple)):
        return len(previous) == len(current) and all(
            exact_snapshot_values_equal(left, right)
            for left, right in zip(previous, current, strict=True)
        )
    if isinstance(previous, dict):
        # Python dict equality ignores insertion order.
        return len(previous) == len(current) and all(
            exact_snapshot_values_equal(left_key, right_key)
            and exact_snapshot_values_equal(left_value, right_value)
            for (left_key, left_value), (right_key, right_value) in zip(
                previous.items(), current.items(), strict=True
            )
        )
    if is_dataclass(previous) and not isinstance(previous, type):
        return all(
            exact_snapshot_values_equal(
                getattr(previous, field.name), getattr(current, field.name)
            )
            for field in fields(previous)
        )
    # Unknown/custom source type: never claim equivalence. The SHA-256
    # fingerprint path remains authoritative for everything unsupported.
    return False


# A release-scoped format identifier prevents replay results produced by earlier
# simulation code from silently becoming authoritative after an integration upgrade.
# Bump this whenever the historical comparison algorithm changes.
PERSISTED_REPLAY_FORMAT = "alpha9.153-historical-replay-v1"


class HistoricalReplayCache:
    """Cache historical day results only when every explicit input is unchanged."""

    def __init__(self, max_days: int = 400) -> None:
        if max_days < 1:
            raise ValueError("max_days must be positive")
        self._max_days = max_days
        self._entries: OrderedDict[str, tuple[bytes, dict[str, Any]]] = OrderedDict()
        # Binary copies are produced from verified, local JSON-like replay
        # results; persisted cache remains normal JSON, never pickle bytes.
        # Keeping a private serialized representation makes read isolation much
        # cheaper than recursively deepcopying every historic slot per scan.
        self._encoded_results: dict[str, bytes] = {}
        self._fast_result_copies = 0
        self._fallback_result_copies = 0
        self._snapshot_hits = 0
        self._snapshot_checks = 0
        self._snapshot_comparison_seconds = 0.0
        self._snapshot_capture_failures = 0
        self._hits = 0
        self._misses = 0
        self._live_evaluations = 0
        self._fingerprint_seconds = 0.0
        self._pickle_fingerprints = 0
        self._legacy_fingerprints = 0
        self._persist_dirty = False
        self._restored_days = 0

    @property
    def status(self) -> dict[str, int | str]:
        return {
            "scope": "historical_day_comparison_only",
            "cached_days": len(self._entries),
            "restored_days": self._restored_days,
            "pending_persist": self._persist_dirty,
            "max_days": self._max_days,
            "hits": self._hits,
            "misses": self._misses,
            "live_evaluations": self._live_evaluations,
            "hardware_writes": "unchanged",
            "result_copy_method": "local_pickle_loads_with_deepcopy_fallback",
            "encoded_result_days": len(self._encoded_results),
            "fast_result_copies": self._fast_result_copies,
            "fallback_result_copies": self._fallback_result_copies,
            "fingerprint_method": "binary_pickle_sha256_with_legacy_fallback",
            "fingerprint_seconds_total": round(self._fingerprint_seconds, 3),
            "pickle_fingerprints": self._pickle_fingerprints,
            "legacy_fingerprints": self._legacy_fingerprints,
            "input_snapshot_hits": self._snapshot_hits,
            "input_snapshot_checks": self._snapshot_checks,
            "input_snapshot_comparison_seconds_total": round(
                self._snapshot_comparison_seconds, 3
            ),
            "input_snapshot_days": 0,
            "input_snapshot_capture_failures": self._snapshot_capture_failures,
            "input_snapshot_policy": "binary_sha256_only_per_historical_day",
        }

    def _remember_encoded_result(self, day: str, value: dict[str, Any]) -> None:
        """Encode only a privately owned result; failure retains deep-copy path."""
        try:
            self._encoded_results[day] = dumps(value, protocol=HIGHEST_PROTOCOL)
        except (PicklingError, TypeError, AttributeError, ValueError, OverflowError):
            self._encoded_results.pop(day, None)

    def _isolated_result(self, day: str, result: dict[str, Any]) -> dict[str, Any]:
        """Never hand callers the cached result or a shared mutable child."""
        encoded = self._encoded_results.get(day)
        if encoded is not None:
            try:
                isolated = loads(encoded)
                if isinstance(isolated, dict):
                    self._fast_result_copies += 1
                    return isolated
            except (TypeError, ValueError, EOFError, ImportError, AttributeError):
                # Result copy only. Cached SHA-256 verification stays intact.
                self._encoded_results.pop(day, None)
        self._fallback_result_copies += 1
        return deepcopy(result)

    @property
    def needs_persist(self) -> bool:
        """Whether new historical calculations require a storage checkpoint."""
        return self._persist_dirty

    def mark_persisted(self) -> None:
        """Acknowledge persistence only after Home Assistant's store saves."""
        self._persist_dirty = False

    def export_state(self) -> dict[str, Any]:
        """Save only bounded historical results and SHA-256 digests, never pickle.

        The stored result is read-only advisory reporting. A restored entry is
        never trusted without recomputing its exact current input fingerprint.
        """
        return {
            "format": PERSISTED_REPLAY_FORMAT,
            "entries": [
                {
                    "day": day,
                    "sha256": fingerprint.hex(),
                    "result": deepcopy(result),
                }
                for day, (fingerprint, result) in self._entries.items()
            ],
        }

    def restore_state(self, payload: Any) -> None:
        """Restore a bounded, validated warm cache after an HA/KEMS restart.

        Corrupt, foreign-version, or malformed entries are ignored. Entries
        cannot authorise physical dispatch: every cache hit still verifies the
        full exact-input SHA-256 fingerprint and only settled days are eligible.
        """
        self._entries.clear()
        self._encoded_results.clear()
        self._restored_days = 0
        self._persist_dirty = False
        if (
            not isinstance(payload, dict)
            or payload.get("format") != PERSISTED_REPLAY_FORMAT
        ):
            return
        records = payload.get("entries")
        if not isinstance(records, list):
            return
        for item in records[-self._max_days :]:
            if not isinstance(item, dict):
                continue
            day = item.get("day")
            digest = item.get("sha256")
            result = item.get("result")
            if not isinstance(day, str) or not isinstance(digest, str):
                continue
            if not isinstance(result, dict) or len(digest) != 64:
                continue
            try:
                parsed_day = date.fromisoformat(day)
                fingerprint = bytes.fromhex(digest)
            except ValueError:
                continue
            if parsed_day.isoformat() != day or len(fingerprint) != 32:
                continue
            self._entries[day] = (fingerprint, deepcopy(result))
            self._remember_encoded_result(day, self._entries[day][1])
            self._entries.move_to_end(day)
        self._restored_days = len(self._entries)

    def _fingerprint(self, inputs: tuple[Any, ...]) -> bytes:
        """Fingerprint exact immutable-in-time values of historical inputs."""
        started = perf_counter()
        try:
            fingerprint = sha256(dumps(inputs, protocol=HIGHEST_PROTOCOL)).digest()
            self._pickle_fingerprints += 1
        except (PicklingError, TypeError, AttributeError, ValueError, OverflowError):
            fingerprint = sha256(repr(inputs).encode("utf-8")).digest()
            self._legacy_fingerprints += 1
        finally:
            self._fingerprint_seconds += perf_counter() - started
        return fingerprint

    def get_cached(
        self,
        *,
        day: date,
        today: date | None,
        projection: bool,
        inputs: tuple[Any, ...],
    ) -> dict[str, Any] | None:
        """Return an exact settled-day hit without scheduling an executor job.

        A miss leaves the normal executor-based evaluation untouched. The
        live day and tomorrow are never served from cache, and changed prices,
        SOC, tariff, configuration or late backfill never reuse stale output.
        """
        if today is None or day >= today or projection:
            return None
        key = day.isoformat()
        cached = self._entries.get(key)
        if cached is None:
            return None
        # Preserve full SHA-256 validation on every historical cache hit;
        # this is cheaper than the recursive deep-snapshot comparison.
        if cached[0] != self._fingerprint(inputs):
            return None
        self._hits += 1
        self._entries.move_to_end(key)
        return self._isolated_result(key, cached[1])

    def evaluate(
        self,
        *,
        day: date,
        today: date | None,
        projection: bool,
        inputs: tuple[Any, ...],
        calculate: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Return isolated historical results, recomputing on any input change.

        Hash the exact repr of source records and the full configuration,
        tariff, independent SOCs and day prices, rather than relying on
        timestamps or object identities. Even incomplete old days are cached
        only until their inputs change; late/backfilled data invalidates them.
        """
        if today is None or day >= today or projection:
            self._live_evaluations += 1
            return calculate()

        # repr() recursively formats every dataclass, datetime and dict into
        # a large temporary string on every cache hit. Binary serialisation
        # preserves the exact input values while avoiding that formatting
        # cost. Only settled historical comparisons use this optimisation:
        # today's physical dispatch and tomorrow's projection always replay.
        key = day.isoformat()
        cached = self._entries.get(key)
        fingerprint = self._fingerprint(inputs)
        if cached is not None and cached[0] == fingerprint:
            self._hits += 1
            self._entries.move_to_end(key)
            return self._isolated_result(key, cached[1])

        self._misses += 1
        result = calculate()
        self._entries[key] = (fingerprint, deepcopy(result))
        self._remember_encoded_result(key, self._entries[key][1])
        self._persist_dirty = True
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_days:
            evicted_day, _ = self._entries.popitem(last=False)
            self._encoded_results.pop(evicted_day, None)
        return result
