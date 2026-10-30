"""Skip only the redundant second Agile settlement replay on unchanged evidence.

Every scan still performs the authoritative pre-control reconciliation; any
post-shadow new/corrected half-hour must republish in the same coordinator scan.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def settled_half_hour_snapshot(
    settled: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Snapshot nested evidence by value, not shared mutable references."""
    return deepcopy(settled)


def settled_half_hours_changed(
    previous: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> bool:
    """Detect new half-hours, revisions, and nested in-place corrections."""
    return previous != current
