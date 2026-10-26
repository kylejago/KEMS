"""Strict value comparison for settled historical replay inputs.

This is an optional faster *positive match* for deep-copied historical inputs.
If any input is unsupported or differs, the caller falls back to the existing
binary pickle SHA-256 fingerprint before considering a cached result. Datetime
folds (BST/GMT transition), ordered dictionaries, floating point signed zeros,
and mutable nested objects must not be silently treated as identical.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime, time, timedelta
from struct import pack
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
