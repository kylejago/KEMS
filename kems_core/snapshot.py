"""KEMS monitoring snapshot."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Snapshot:
    """One observation of the home."""

    timestamp: datetime = field(default_factory=datetime.now)

    #
    # Electricity
    #
    current_import_rate: float | None = None
    next_import_rate: float | None = None

    off_peak: bool | None = None
    intelligent_slot: bool | None = None

    next_offpeak_start: datetime | None = None
    offpeak_end: datetime | None = None

    #
    # EV
    #
    ev_connected: bool | None = None
    ev_charging: bool | None = None
    ev_power_kw: float | None = None
    ev_soc: float | None = None

    #
    # House
    #
    house_load_kw: float | None = None

    #
    # Battery
    #
    battery_soc: float | None = None
    battery_power_kw: float | None = None

    #
    # Solar
    #
    solar_power_kw: float | None = None

    #
    # Grid
    #
    grid_import_kw: float | None = None
    grid_export_kw: float | None = None
