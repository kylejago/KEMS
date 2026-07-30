"""Ohme models."""

from dataclasses import dataclass


@dataclass(slots=True)
class OhmeState:
    """Current state of the charger."""

    connected: bool = False
    charging: bool = False

    power_kw: float | None = None
    vehicle_soc: float | None = None
