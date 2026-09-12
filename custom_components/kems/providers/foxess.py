"""FoxESS Modbus state provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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
        effective_ages: dict[str, float] = {}
        stale: set[str] = set()
        registry = er.async_get(self._hass)
        cohort_entity_ids = tuple(
            dict.fromkeys(
                entity_id
                for entity_id in (
                    self._entities.house_load_kw,
                    self._entities.battery_soc,
                    self._entities.battery_power_kw,
                    self._entities.battery_voltage,
                    self._entities.battery_current,
                    self._entities.solar_power_kw,
                    self._entities.grid_import_kw,
                    self._entities.grid_export_kw,
                )
                if entity_id
            )
        )

        def age_for(logical_name: str, entity_id: str | None) -> float | None:
            age = self._report_age_seconds(entity_id, reference)
            if age is not None:
                ages[logical_name] = round(age, 1)
            return age

        def same_device_cohort_age(entity_id: str | None) -> float | None:
            """Return a fresh sibling age proving this FoxESS device is still live.

            FoxESS Modbus only writes a Home Assistant sensor state when its value
            changes. Therefore an unchanged sensor can have an old ``last_reported``
            timestamp even while the inverter is being polled successfully. A stale
            looking value is accepted only when another numeric entity from the same
            ``foxess_modbus`` device has reported within the normal freshness window.
            """
            if not entity_id:
                return None
            target = registry.async_get(entity_id)
            if (
                target is None
                or target.platform != "foxess_modbus"
                or target.device_id is None
            ):
                return None

            sibling_ages: list[float] = []
            for sibling_id in cohort_entity_ids:
                if sibling_id == entity_id:
                    continue
                sibling = registry.async_get(sibling_id)
                if (
                    sibling is None
                    or sibling.platform != "foxess_modbus"
                    or sibling.device_id != target.device_id
                    or self._float(sibling_id) is None
                ):
                    continue
                sibling_age = self._report_age_seconds(sibling_id, reference)
                if sibling_age is not None and sibling_age <= self._stale_data_seconds:
                    sibling_ages.append(sibling_age)
            return min(sibling_ages) if sibling_ages else None

        def effective_age(
            entity_id: str | None,
            raw_age: float | None,
        ) -> float | None:
            if raw_age is None or raw_age <= self._stale_data_seconds:
                return raw_age
            return same_device_cohort_age(entity_id)

        def source_is_usable(
            logical_name: str,
            entity_id: str | None,
        ) -> bool:
            age = age_for(logical_name, entity_id)
            if age is None:
                return True
            usable_age = effective_age(entity_id, age)
            if usable_age is not None:
                effective_ages[logical_name] = round(usable_age, 1)
                return True
            effective_ages[logical_name] = round(age, 1)
            stale.add(logical_name)
            return False

        def fresh_power(logical_name: str, entity_id: str | None) -> float | None:
            if not source_is_usable(logical_name, entity_id):
                return None
            return self._power_kw(entity_id)

        def fresh_float(logical_name: str, entity_id: str | None) -> float | None:
            if not source_is_usable(logical_name, entity_id):
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
            component_effective_ages = [
                effective_age(entity_id, age)
                for age, entity_id in (
                    (voltage_age, self._entities.battery_voltage),
                    (current_age, self._entities.battery_current),
                )
                if age is not None
            ]
            components_usable = component_ages and all(
                age is not None for age in component_effective_ages
            )
            if components_usable:
                derived = calculate_battery_power_kw(
                    self._float(self._entities.battery_voltage),
                    self._float(self._entities.battery_current),
                )
                if derived is not None:
                    battery_power = derived
                    ages["battery_power_kw"] = round(max(component_ages), 1)
                    effective_ages["battery_power_kw"] = round(
                        max(age for age in component_effective_ages if age is not None),
                        1,
                    )
                    stale.discard("battery_power_kw")
            elif component_ages and battery_power is None:
                ages["battery_power_kw"] = round(max(component_ages), 1)
                effective_ages["battery_power_kw"] = round(max(component_ages), 1)
                stale.add("battery_power_kw")

        grid = normalise_grid_power(raw_grid_import, raw_grid_export)
        max_age = max(effective_ages.values()) if effective_ages else None
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
