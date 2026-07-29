"""KEMS monitoring snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Snapshot:
    """One observation of the home."""

    timestamp: datetime

    electricity_rate: float | None = None
    cheap_rate: bool | None = None

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
