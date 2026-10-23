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
from typing import Any


class HistoricalReplayCache:
    """Cache historical day results only when every explicit input is unchanged."""

    def __init__(self, max_days: int = 400) -> None:
        if max_days < 1:
            raise ValueError("max_days must be positive")
        self._max_days = max_days
        self._entries: OrderedDict[str, tuple[str, dict[str, Any]]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._live_evaluations = 0

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
        }

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

        fingerprint = sha256(repr(inputs).encode("utf-8")).hexdigest()
        key = day.isoformat()
        cached = self._entries.get(key)
        if cached is not None and cached[0] == fingerprint:
            self._hits += 1
            self._entries.move_to_end(key)
            return deepcopy(cached[1])

        self._misses += 1
        result = calculate()
        self._entries[key] = (fingerprint, deepcopy(result))
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_days:
            self._entries.popitem(last=False)
        return result
