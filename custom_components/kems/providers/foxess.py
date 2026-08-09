"""FoxESS Modbus state provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..kems_core import calculate_battery_power_kw, normalise_grid_power
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
    raw_grid_import_kw: float | None = None
    raw_grid_export_kw: float | None = None
    grid_flow_mode: str = "no_grid_source"
    source_age_seconds: dict[str, float] = field(default_factory=dict)
    stale_fields: tuple[str, ...] = ()
    source_data_age_seconds: float | None = None


class FoxESSProvider(HomeAssistantStateReader):
    """Read data from configured FoxESS Modbus entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entities: KEMSEntities,
        stale_data_seconds: int = 180,
    ) -> None:
        """Initialise the provider."""
        super().__init__(hass)
        self._entities = entities
        self._stale_data_seconds = max(int(stale_data_seconds), 30)

    def get_state(self, now: datetime | None = None) -> FoxESSState:
        """Return the current FoxESS observation, rejecting stale live data."""
        reference = now or dt_util.now()
        ages: dict[str, float] = {}
        stale: set[str] = set()

        def age_for(logical_name: str, entity_id: str | None) -> float | None:
            age = self._report_age_seconds(entity_id, reference)
            if age is not None:
                ages[logical_name] = round(age, 1)
            return age

        def fresh_power(logical_name: str, entity_id: str | None) -> float | None:
            age = age_for(logical_name, entity_id)
            if age is not None and age > self._stale_data_seconds:
                stale.add(logical_name)
                return None
            return self._power_kw(entity_id)

        def fresh_float(logical_name: str, entity_id: str | None) -> float | None:
            age = age_for(logical_name, entity_id)
            if age is not None and age > self._stale_data_seconds:
                stale.add(logical_name)
                return None
            return self._float(entity_id)

        house_load = fresh_power("house_load_kw", self._entities.house_load_kw)
        battery_soc = fresh_float("battery_soc", self._entities.battery_soc)
        solar_power = fresh_power("solar_power_kw", self._entities.solar_power_kw)
        raw_grid_import = fresh_power("grid_import_kw", self._entities.grid_import_kw)
        raw_grid_export = fresh_power("grid_export_kw", self._entities.grid_export_kw)

        battery_power = fresh_power(
            "battery_power_kw",
            self._entities.battery_power_kw,
        )
        if battery_power is None:
            voltage_age = self._report_age_seconds(
                self._entities.battery_voltage,
                reference,
            )
            current_age = self._report_age_seconds(
                self._entities.battery_current,
                reference,
            )
            component_ages = [
                age for age in (voltage_age, current_age) if age is not None
            ]
            if component_ages and all(
                age <= self._stale_data_seconds for age in component_ages
            ):
                derived = calculate_battery_power_kw(
                    self._float(self._entities.battery_voltage),
                    self._float(self._entities.battery_current),
                )
                if derived is not None:
                    battery_power = derived
                    ages["battery_power_kw"] = round(max(component_ages), 1)
                    stale.discard("battery_power_kw")
            elif component_ages and battery_power is None:
                ages["battery_power_kw"] = round(max(component_ages), 1)
                stale.add("battery_power_kw")

        grid = normalise_grid_power(raw_grid_import, raw_grid_export)
        max_age = max(ages.values()) if ages else None
        return FoxESSState(
            house_load_kw=house_load,
            battery_soc=battery_soc,
            battery_power_kw=battery_power,
            solar_power_kw=solar_power,
            grid_import_kw=grid.import_kw,
            grid_export_kw=grid.export_kw,
            raw_grid_import_kw=grid.raw_import_kw,
            raw_grid_export_kw=grid.raw_export_kw,
            grid_flow_mode=grid.mode,
            source_age_seconds=ages,
            stale_fields=tuple(sorted(stale)),
            source_data_age_seconds=max_age,
        )
