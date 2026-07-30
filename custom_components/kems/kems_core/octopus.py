"""Octopus Energy observation model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class OctopusState:
    """Current state read from Octopus Energy entities."""

    current_rate_pence: float | None = None
    next_rate_pence: float | None = None
    off_peak: bool | None = None
    intelligent_slot: bool | None = None
    next_offpeak_start: datetime | None = None
    offpeak_end: datetime | None = None
