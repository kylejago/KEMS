"""Configured Home Assistant entity mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..const import (
    CONF_BATTERY_CURRENT,
    CONF_BATTERY_POWER,
    CONF_BATTERY_SOC,
    CONF_BATTERY_VOLTAGE,
    CONF_CURRENT_EXPORT_RATE,
    CONF_CURRENT_IMPORT_RATE,
    CONF_EV_CHARGING,
    CONF_EV_CONNECTED,
    CONF_EV_POWER,
    CONF_EV_SOC,
    CONF_EV_STATUS,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_HOUSE_LOAD,
    CONF_INTELLIGENT_SLOT,
    CONF_NEXT_IMPORT_RATE,
    CONF_NEXT_OFFPEAK_START,
    CONF_OFF_PEAK,
    CONF_OFFPEAK_END,
    CONF_SOLAR_POWER,
    ENTITY_MAPPING_KEYS,
)


@dataclass(frozen=True, slots=True)
class KEMSEntities:
    """Entity IDs observed by KEMS."""

    current_import_rate: str | None = None
    next_import_rate: str | None = None
    current_export_rate: str | None = None
    off_peak: str | None = None
    intelligent_slot: str | None = None
    next_offpeak_start: str | None = None
    offpeak_end: str | None = None
    ev_status: str | None = None
    ev_connected: str | None = None
    ev_charging: str | None = None
    ev_power_kw: str | None = None
    ev_soc: str | None = None
    house_load_kw: str | None = None
    battery_soc: str | None = None
    battery_power_kw: str | None = None
    battery_voltage: str | None = None
    battery_current: str | None = None
    solar_power_kw: str | None = None
    grid_import_kw: str | None = None
    grid_export_kw: str | None = None

    @classmethod
    def from_entry_data(cls, data: dict[str, Any]) -> KEMSEntities:
        """Build an entity map from config-entry data."""
        return cls(
            current_import_rate=data.get(CONF_CURRENT_IMPORT_RATE),
            next_import_rate=data.get(CONF_NEXT_IMPORT_RATE),
            current_export_rate=data.get(CONF_CURRENT_EXPORT_RATE),
            off_peak=data.get(CONF_OFF_PEAK),
            intelligent_slot=data.get(CONF_INTELLIGENT_SLOT),
            next_offpeak_start=data.get(CONF_NEXT_OFFPEAK_START),
            offpeak_end=data.get(CONF_OFFPEAK_END),
            ev_status=data.get(CONF_EV_STATUS),
            ev_connected=data.get(CONF_EV_CONNECTED),
            ev_charging=data.get(CONF_EV_CHARGING),
            ev_power_kw=data.get(CONF_EV_POWER),
            ev_soc=data.get(CONF_EV_SOC),
            house_load_kw=data.get(CONF_HOUSE_LOAD),
            battery_soc=data.get(CONF_BATTERY_SOC),
            battery_power_kw=data.get(CONF_BATTERY_POWER),
            battery_voltage=data.get(CONF_BATTERY_VOLTAGE),
            battery_current=data.get(CONF_BATTERY_CURRENT),
            solar_power_kw=data.get(CONF_SOLAR_POWER),
            grid_import_kw=data.get(CONF_GRID_IMPORT),
            grid_export_kw=data.get(CONF_GRID_EXPORT),
        )

    def configured_snapshot_fields(self) -> set[str]:
        """Return logical snapshot fields with configured source data."""
        fields: set[str] = set()
        direct = {
            "current_import_rate": self.current_import_rate,
            "next_import_rate": self.next_import_rate,
            "current_export_rate": self.current_export_rate,
            "off_peak": self.off_peak,
            "intelligent_slot": self.intelligent_slot,
            "next_offpeak_start": self.next_offpeak_start,
            "offpeak_end": self.offpeak_end,
            "ev_power_kw": self.ev_power_kw,
            "ev_soc": self.ev_soc,
            "house_load_kw": self.house_load_kw,
            "battery_soc": self.battery_soc,
            "solar_power_kw": self.solar_power_kw,
            "grid_import_kw": self.grid_import_kw,
            "grid_export_kw": self.grid_export_kw,
        }
        fields.update(key for key, value in direct.items() if value is not None)

        if self.ev_status or self.ev_connected:
            fields.add("ev_connected")
        if self.ev_status or self.ev_charging:
            fields.add("ev_charging")
        if self.battery_power_kw or (self.battery_voltage and self.battery_current):
            fields.add("battery_power_kw")
        return fields

    def as_dict(self) -> dict[str, str]:
        """Return configured mappings only."""
        return {
            key: value
            for key in ENTITY_MAPPING_KEYS
            if (value := getattr(self, key, None)) is not None
        }
