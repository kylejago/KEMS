"""Configured Home Assistant entity mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..const import (
    CONF_CURRENT_IMPORT_RATE,
    CONF_EV_CHARGING,
    CONF_EV_CONNECTED,
    CONF_EV_POWER,
    CONF_EV_SOC,
    CONF_INTELLIGENT_SLOT,
    CONF_NEXT_IMPORT_RATE,
    CONF_NEXT_OFFPEAK_START,
    CONF_OFF_PEAK,
    CONF_OFFPEAK_END,
)


@dataclass(frozen=True, slots=True)
class KEMSEntities:
    """Entity IDs selected in the KEMS config flow."""

    current_import_rate: str
    next_import_rate: str
    off_peak: str
    intelligent_slot: str
    next_offpeak_start: str
    offpeak_end: str
    ev_connected: str | None = None
    ev_charging: str | None = None
    ev_power: str | None = None
    ev_soc: str | None = None

    @classmethod
    def from_entry_data(cls, data: dict[str, Any]) -> KEMSEntities:
        """Build an entity map from config-entry data."""
        return cls(
            current_import_rate=data[CONF_CURRENT_IMPORT_RATE],
            next_import_rate=data[CONF_NEXT_IMPORT_RATE],
            off_peak=data[CONF_OFF_PEAK],
            intelligent_slot=data[CONF_INTELLIGENT_SLOT],
            next_offpeak_start=data[CONF_NEXT_OFFPEAK_START],
            offpeak_end=data[CONF_OFFPEAK_END],
            ev_connected=data.get(CONF_EV_CONNECTED),
            ev_charging=data.get(CONF_EV_CHARGING),
            ev_power=data.get(CONF_EV_POWER),
            ev_soc=data.get(CONF_EV_SOC),
        )
