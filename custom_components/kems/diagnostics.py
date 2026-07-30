"""Diagnostics support for KEMS."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import KEMSCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a KEMS config entry."""
    coordinator = cast(KEMSCoordinator, entry.runtime_data)
    return {
        "configured_entities": dict(entry.data),
        "snapshot": asdict(coordinator.data),
        "last_update_success": coordinator.last_update_success,
    }
