"""Small, dependency-free KEMS release-version ordering helpers."""

from __future__ import annotations

import re
from typing import Any

_VERSION_PATTERN = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<stage>alpha|beta|rc)(?P<stage_number>\d+)"
    r"(?P<tail>(?:[.-]\d+)*))?$",
    re.IGNORECASE,
)
_STAGE_ORDER = {"alpha": 0, "beta": 1, "rc": 2}


def normalise_version(value: Any) -> str:
    """Normalise a conventional leading ``v`` without changing the release."""
    text = str(value or "").strip()
    if text.lower().startswith("v") and len(text) > 1 and text[1].isdigit():
        return text[1:]
    return text


def version_order_key(
    value: Any,
) -> tuple[int, int, int, int, int, tuple[int, ...]] | None:
    """Return an ordering key for KEMS semantic alpha/beta/rc/stable releases."""
    match = _VERSION_PATTERN.fullmatch(normalise_version(value))
    if match is None:
        return None

    stage = match.group("stage")
    stage_rank = 3 if stage is None else _STAGE_ORDER[stage.lower()]
    stage_number = int(match.group("stage_number") or 0)
    tail = tuple(int(part) for part in re.findall(r"\d+", match.group("tail") or ""))
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        stage_rank,
        stage_number,
        tail,
    )


def version_relation(candidate: Any, current: Any) -> int | None:
    """Compare candidate with current: 1 newer, 0 equal, -1 older, None unknown."""
    candidate_key = version_order_key(candidate)
    current_key = version_order_key(current)
    if candidate_key is None or current_key is None:
        return None
    return (candidate_key > current_key) - (candidate_key < current_key)


def version_is_newer(candidate: Any, current: Any) -> bool:
    """Return whether candidate is a safely-ordered newer KEMS release."""
    return version_relation(candidate, current) == 1
