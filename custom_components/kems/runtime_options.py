"""Helpers for safe runtime option changes from KEMS control-lab entities."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_set_runtime_option(
    hass: HomeAssistant,
    entry: ConfigEntry,
    key: str,
    value: Any,
) -> None:
    """Persist one option and reload KEMS so every engine sees it atomically."""
    options = {**dict(entry.options), key: value}
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_reload(entry.entry_id)
