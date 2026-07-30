"""Octopus Intelligent models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class OctopusState:
    """Current state of the Octopus integration."""

    current_rate: float | None = None
    next_rate: float | None = None

    off_peak: bool = False

    intelligent_slot: bool = False
    planned_dispatch: bool = False

    next_offpeak_start: datetime | None = None
    offpeak_end: datetime | None = None
