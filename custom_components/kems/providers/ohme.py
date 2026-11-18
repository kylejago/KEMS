"""Ohme state provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..kems_core.ohme import combine_charger_evidence
from .base import HomeAssistantStateReader
from .entity_map import KEMSEntities

DEFAULT_OHME_STALE_DATA_SECONDS = 180


@dataclass(frozen=True, slots=True)
class OhmeState:
    """Current Ohme observation."""

    status: str | None = None
    charge_mode: str | None = None
    connected: bool | None = None
    charging: bool | None = None
    power_kw: float | None = None
    power_age_seconds: float | None = None
    vehicle_soc: float | None = None


class OhmeProvider(HomeAssistantStateReader):
    """Read fresh data from all configured Ohme confirmation entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entities: KEMSEntities,
        stale_data_seconds: int = DEFAULT_OHME_STALE_DATA_SECONDS,
    ) -> None:
        """Initialise the provider."""
        super().__init__(hass)
        self._entities = entities
        self._stale_data_seconds = max(int(stale_data_seconds), 30)

    def get_state(self, now: datetime | None = None) -> OhmeState:
        """Return current Ohme state while failing closed on stale evidence."""
        reference = now or dt_util.now()

        def fresh_text(entity_id: str | None) -> str | None:
            if not self._source_is_fresh(
                entity_id,
                self._stale_data_seconds,
                reference,
            ):
                return None
            return self._text(entity_id)

        def fresh_bool(entity_id: str | None) -> bool | None:
            if not self._source_is_fresh(
                entity_id,
                self._stale_data_seconds,
                reference,
            ):
                return None
            return self._bool(entity_id)

        status = fresh_text(self._entities.ev_status)
        charge_mode = fresh_text(self._entities.ohme_charge_mode)
        power_kw = self._fresh_power_kw(
            self._entities.ev_power_kw,
            self._stale_data_seconds,
            reference,
        )
        power_age = self._report_age_seconds(self._entities.ev_power_kw, reference)
        vehicle_soc = self._fresh_float(
            self._entities.ev_soc,
            self._stale_data_seconds,
            reference,
        )
        connected, charging = combine_charger_evidence(
            status=status,
            explicit_connected=fresh_bool(self._entities.ev_connected),
            explicit_charging=fresh_bool(self._entities.ev_charging),
            power_kw=power_kw,
        )

        return OhmeState(
            status=status,
            charge_mode=charge_mode,
            connected=connected,
            charging=charging,
            power_kw=power_kw,
            power_age_seconds=(
                round(power_age, 1)
                if power_kw is not None and power_age is not None
                else None
            ),
            vehicle_soc=vehicle_soc,
        )
