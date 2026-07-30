"""Driver registry."""

from __future__ import annotations

from kems_core.drivers.battery import BatteryDriver


class DriverRegistry:
    """Stores active drivers."""

    def __init__(self) -> None:
        self._battery: BatteryDriver | None = None

    def register_battery(self, driver: BatteryDriver) -> None:
        """Register a battery driver."""
        self._battery = driver

    @property
    def battery(self) -> BatteryDriver | None:
        """Return battery driver."""
        return self._battery
