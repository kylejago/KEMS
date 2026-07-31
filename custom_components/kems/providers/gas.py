"""Octopus gas state provider."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from .base import HomeAssistantStateReader
from .entity_map import KEMSEntities


@dataclass(frozen=True, slots=True)
class GasState:
    """Current gas tariff, meter, and daily-total observation."""

    current_rate: float | None = None
    standing_charge: float | None = None
    meter_total_kwh: float | None = None
    usage_today_kwh: float | None = None
    cost_today_pence: float | None = None


class GasProvider(HomeAssistantStateReader):
    """Read gas data from configured Octopus entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entities: KEMSEntities,
        gas_kwh_per_m3: float,
    ) -> None:
        """Initialise the provider."""
        super().__init__(hass)
        self._entities = entities
        self._gas_kwh_per_m3 = gas_kwh_per_m3

    def get_state(self) -> GasState:
        """Return the current gas observation."""
        return GasState(
            current_rate=self._rate_pence(self._entities.gas_current_rate),
            standing_charge=self._money_pence(self._entities.gas_standing_charge),
            meter_total_kwh=self._energy_kwh(
                self._entities.gas_meter_total,
                self._gas_kwh_per_m3,
            ),
            usage_today_kwh=self._energy_kwh(
                self._entities.gas_usage_today,
                self._gas_kwh_per_m3,
            ),
            cost_today_pence=self._money_pence(self._entities.gas_cost_today),
        )
