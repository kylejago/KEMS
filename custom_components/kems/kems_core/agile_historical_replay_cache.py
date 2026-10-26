"""Bounded exact-input reuse for settled Agile historical comparison days.

Live/current-day and tomorrow projections never use this cache. It changes
no prices, export dispatch, physical energy authority, or hardware writes.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from datetime import date
from hashlib import sha256
from pickle import HIGHEST_PROTOCOL, PicklingError, dumps
from time import perf_counter
from typing import Any

from .agile_exact_snapshot_equality import exact_snapshot_values_equal


class HistoricalReplayCache:
    """Cache historical day results only when every explicit input is unchanged."""

    def __init__(self, max_days: int = 400) -> None:
        if max_days < 1:
            raise ValueError("max_days must be positive")
        self._max_days = max_days
        self._entries: OrderedDict[str, tuple[str, dict[str, Any]]] = OrderedDict()
        # Copies of only the bounded historical inputs, never live or future.
        # No shared mutable references may survive an input mutation.
        self._input_snapshots: dict[str, tuple[Any, ...]] = {}
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

    @property
    def status(self) -> dict[str, int | str]:
        return {
            "scope": "historical_day_comparison_only",
            "cached_days": len(self._entries),
            "max_days": self._max_days,
            "hits": self._hits,
            "misses": self._misses,
            "live_evaluations": self._live_evaluations,
            "hardware_writes": "unchanged",
            "fingerprint_method": "binary_pickle_sha256_with_legacy_fallback",
            "fingerprint_seconds_total": round(self._fingerprint_seconds, 3),
            "pickle_fingerprints": self._pickle_fingerprints,
            "legacy_fingerprints": self._legacy_fingerprints,
            "input_snapshot_hits": self._snapshot_hits,
            "input_snapshot_checks": self._snapshot_checks,
            "input_snapshot_comparison_seconds_total": round(
                self._snapshot_comparison_seconds, 3
            ),
            "input_snapshot_days": len(self._input_snapshots),
            "input_snapshot_capture_failures": self._snapshot_capture_failures,
            "input_snapshot_policy": "strict_value_then_original_sha256_fallback",
        }

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

    def _unchanged_snapshot(self, key: str, inputs: tuple[Any, ...]) -> bool:
        """Cheap exact-value hit; unsupported types fall back to SHA-256."""
        previous = self._input_snapshots.get(key)
        if previous is None:
            return False
        started = perf_counter()
        self._snapshot_checks += 1
        try:
            matches = exact_snapshot_values_equal(previous, inputs)
        except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
            matches = False
        finally:
            self._snapshot_comparison_seconds += perf_counter() - started
        if matches:
            self._snapshot_hits += 1
        return matches

    def _capture_snapshot(self, key: str, inputs: tuple[Any, ...]) -> None:
        """Capture only historical inputs, preserving late-backfill invalidation."""
        try:
            self._input_snapshots[key] = deepcopy(inputs)
        except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
            self._input_snapshots.pop(key, None)
            self._snapshot_capture_failures += 1

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
        # On changed/unsupported input, preserve the original SHA-256 gate.
        if not self._unchanged_snapshot(key, inputs) and cached[0] != self._fingerprint(
            inputs
        ):
            return None
        self._hits += 1
        self._entries.move_to_end(key)
        return deepcopy(cached[1])

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
        if cached is not None and self._unchanged_snapshot(key, inputs):
            self._hits += 1
            self._entries.move_to_end(key)
            return deepcopy(cached[1])
        fingerprint = self._fingerprint(inputs)
        if cached is not None and cached[0] == fingerprint:
            self._hits += 1
            self._entries.move_to_end(key)
            return deepcopy(cached[1])

        self._misses += 1
        result = calculate()
        self._entries[key] = (fingerprint, deepcopy(result))
        self._capture_snapshot(key, inputs)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_days:
            removed_day, _ = self._entries.popitem(last=False)
            self._input_snapshots.pop(removed_day, None)
        return result
