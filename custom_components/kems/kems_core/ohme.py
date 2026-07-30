"""Ohme observation model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OhmeState:
    """Current state read from Ohme entities."""

    connected: bool | None = None
    charging: bool | None = None
    power_kw: float | None = None
    vehicle_soc: float | None = None
