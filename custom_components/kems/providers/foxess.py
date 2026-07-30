"""FoxESS Modbus state provider."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from ..kems_core import calculate_battery_power_kw
from .base import HomeAssistantStateReader
from .entity_map import KEMSEntities


@dataclass(frozen=True, slots=True)
class FoxESSState:
    """Current inverter, battery, solar, and grid observation."""

    house_load_kw: float | None = None
    battery_soc: float | None = None
    battery_power_kw: float | None = None
    solar_power_kw: float | None = None
    grid_import_kw: float | None = None
    grid_export_kw: float | None = None


class FoxESSProvider(HomeAssistantStateReader):
    """Read data from configured FoxESS Modbus entities."""

    def __init__(self, hass: HomeAssistant, entities: KEMSEntities) -> None:
        """Initialise the provider."""
        super().__init__(hass)
        self._entities = entities

    def get_state(self) -> FoxESSState:
        """Return the current FoxESS observation."""
        battery_power = self._power_kw(self._entities.battery_power_kw)
        if battery_power is None:
            battery_power = calculate_battery_power_kw(
                self._float(self._entities.battery_voltage),
                self._float(self._entities.battery_current),
            )
        return FoxESSState(
            house_load_kw=self._power_kw(self._entities.house_load_kw),
            battery_soc=self._float(self._entities.battery_soc),
            battery_power_kw=battery_power,
            solar_power_kw=self._power_kw(self._entities.solar_power_kw),
            grid_import_kw=self._power_kw(self._entities.grid_import_kw),
            grid_export_kw=self._power_kw(self._entities.grid_export_kw),
        )
