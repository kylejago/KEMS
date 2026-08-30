"""Ohme state provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..kems_core import interpret_charger_status
from .base import HomeAssistantStateReader
from .entity_map import KEMSEntities

DEFAULT_OHME_STALE_DATA_SECONDS = 180


@dataclass(frozen=True, slots=True)
class OhmeState:
    """Current Ohme observation."""

    status: str | None = None
    connected: bool | None = None
    charging: bool | None = None
    power_kw: float | None = None
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
        power_kw = self._fresh_power_kw(
            self._entities.ev_power_kw,
            self._stale_data_seconds,
            reference,
        )
        vehicle_soc = self._fresh_float(
            self._entities.ev_soc,
            self._stale_data_seconds,
            reference,
        )
        status_connected, status_charging = interpret_charger_status(status)
        explicit_connected = fresh_bool(self._entities.ev_connected)
        explicit_charging = fresh_bool(self._entities.ev_charging)

        connected_signals = [
            value
            for value in (
                status_connected if status is not None else None,
                explicit_connected,
            )
            if value is not None
        ]
        charging_signals = [
            value
            for value in (
                status_charging if status is not None else None,
                explicit_charging,
            )
            if value is not None
        ]

        connected = all(connected_signals) if connected_signals else None
        charging = all(charging_signals) if charging_signals else None

        if power_kw is not None and power_kw > 0.1:
            if connected is None:
                connected = True
            if charging is None:
                charging = True

        return OhmeState(
            status=status,
            connected=connected,
            charging=charging,
            power_kw=power_kw,
            vehicle_soc=vehicle_soc,
        )
