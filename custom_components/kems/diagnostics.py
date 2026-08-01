"""Diagnostics support for KEMS."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import KEMSCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return non-secret KEMS diagnostics."""
    coordinator: KEMSCoordinator = entry.runtime_data
    data = coordinator.data
    return {
        "configured_entities": coordinator.entities.as_dict(),
        "options": dict(entry.options),
        "phase": data.phase,
        "snapshot": data.snapshot.to_dict(),
        "learning": asdict(data.learned),
        "gas": asdict(data.gas),
        "advice": {
            "primary": data.advice.primary.to_dict(),
            "items": [item.to_dict() for item in data.advice.items],
        },
        "simulation": asdict(data.simulation),
        "whole_home": asdict(data.whole_home),
        "lifetime": data.lifetime.to_dict(),
        "roi": asdict(data.roi),
        "quality": asdict(data.quality),
        "history_samples": data.history_samples,
        "last_update_success": coordinator.last_update_success,
    }
