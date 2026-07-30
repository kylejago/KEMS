"""KEMS monitoring snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class Snapshot:
    """One read-only observation of the home energy system."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    current_import_rate: float | None = None
    next_import_rate: float | None = None
    off_peak: bool | None = None
    intelligent_slot: bool | None = None
    next_offpeak_start: datetime | None = None
    offpeak_end: datetime | None = None

    ev_connected: bool | None = None
    ev_charging: bool | None = None
    ev_power_kw: float | None = None
    ev_soc: float | None = None

    house_load_kw: float | None = None
    battery_soc: float | None = None
    battery_power_kw: float | None = None
    solar_power_kw: float | None = None
    grid_import_kw: float | None = None
    grid_export_kw: float | None = None
