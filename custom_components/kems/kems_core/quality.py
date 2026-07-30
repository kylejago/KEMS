"""Data-quality scoring for KEMS."""

from __future__ import annotations

from dataclasses import fields

from .models import DataQuality, Snapshot

IMPORTANT_FIELDS = (
    "current_import_rate",
    "off_peak",
    "house_load_kw",
    "battery_soc",
    "solar_power_kw",
    "grid_import_kw",
)


def assess_quality(snapshot: Snapshot, configured_fields: set[str]) -> DataQuality:
    """Score configured and currently available source fields."""
    snapshot_fields = {field.name for field in fields(snapshot)}
    configured = sorted(configured_fields & snapshot_fields)
    available = [name for name in configured if getattr(snapshot, name) is not None]
    missing = tuple(name for name in configured if name not in available)

    if not configured:
        return DataQuality(score=0.0, configured=0, available=0)

    score = 100 * len(available) / len(configured)
    important_missing = sum(
        1 for name in IMPORTANT_FIELDS if name in configured and name in missing
    )
    score = max(score - important_missing * 5, 0.0)
    return DataQuality(
        score=round(score, 1),
        configured=len(configured),
        available=len(available),
        missing_fields=missing,
    )
