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


def needs_full_tomorrow_republication(changes: list[str]) -> bool:
    """Require an expensive republish only for changes to published plans.

    A handoff-only change already lives in the manager's authoritative state.
    The synchronous settlement owner will issue the final full publication
    after its remaining flow and deadline overlays run. Re-running every
    publishing wrapper merely to expose interim handoff metadata is redundant.
    Unknown/future change kinds deliberately require a full publication.
    """
    return any(change != "tomorrow_soc_handoff" for change in changes)
