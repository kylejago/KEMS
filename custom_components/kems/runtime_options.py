"""Helpers for safe runtime option changes from KEMS control-lab entities."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_set_runtime_options(
    hass: HomeAssistant,
    entry: ConfigEntry,
    changes: Mapping[str, Any],
) -> None:
    """Persist related options and reload KEMS once so engines see them atomically."""
    options = {**dict(entry.options), **dict(changes)}
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_set_runtime_option(
    hass: HomeAssistant,
    entry: ConfigEntry,
    key: str,
    value: Any,
) -> None:
    """Persist one option and reload KEMS so every engine sees it atomically."""
    await async_set_runtime_options(hass, entry, {key: value})
