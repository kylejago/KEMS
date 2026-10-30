"""Exact-write coalescing exclusively inside one synchronous Agile settlement pass.

All settlement math, every reporting overlay and every publication function still
run in their original order. Only a second (or later) byte-for-byte-equivalent
state/attribute write to the same HA entity is suppressed. No time-based cache:
new slot, SOC, tariff or other attribute changes always pass through immediately.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class SettlementPublicationScope:
    """Bounded, read-only counters; never saved or involved in control."""

    seen: set[str] = field(default_factory=set)
    attempted: int = 0
    compared: int = 0
    skipped_identical: int = 0
    written: int = 0
    comparison_seconds: float = 0.0

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def summary(self) -> dict[str, float | int]:
        return {
            "attempted": self.attempted,
            "compared": self.compared,
            "skipped_identical": self.skipped_identical,
            "written": self.written,
            "comparison_seconds": round(self.comparison_seconds, 3),
        }


@contextmanager
def coalesce_identical_settlement_publications(
    manager: Any,
) -> Iterator[SettlementPublicationScope]:
    """Keep exact-value checking strictly scoped to one synchronous scan phase.

    No async boundary, global monkey patch, delayed queue, or reordered write.
    On any exception, reset the scope and preserve the existing failure path.
    """
    previous = getattr(manager, "_kems_settlement_publication_scope", None)
    if previous is not None:
        yield previous
        return
    scope = SettlementPublicationScope()
    manager._kems_settlement_publication_scope = scope
    try:
        yield scope
    finally:
        manager._kems_settlement_publication_scope = None
