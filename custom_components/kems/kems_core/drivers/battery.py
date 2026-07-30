"""Battery driver interface."""

from __future__ import annotations

from abc import abstractmethod

from ..models import BatteryState
from .base import Driver


class BatteryDriver(Driver):
    """Abstract battery driver."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the battery driver name."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Return True if the battery is available."""

    @abstractmethod
    async def get_state(self) -> BatteryState:
        """Return the current battery state."""

    @abstractmethod
    async def charge(self, power_kw: float) -> None:
        """Charge battery."""

    @abstractmethod
    async def discharge(self, power_kw: float) -> None:
        """Discharge battery."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop all battery activity."""
