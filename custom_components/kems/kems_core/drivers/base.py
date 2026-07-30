"""Base driver interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Driver(ABC):
    """Base class for all KEMS drivers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the human-readable driver name."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Return True if the driver is currently available."""
