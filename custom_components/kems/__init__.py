"""KEMS."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

PLATFORMS = [
    Platform.SENSOR,
]


async def async_setup(
    hass: HomeAssistant,
    config: dict,
) -> bool:
    """Set up KEMS."""

    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up KEMS."""

    await hass.config_entries.async_forward_entry_setups(
        entry,
        PLATFORMS,
    )

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload KEMS."""

    return await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )
