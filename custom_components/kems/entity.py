"""Base entity for KEMS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME

if TYPE_CHECKING:
    from .coordinator import KEMSCoordinator


def _integration_version() -> str:
    """Read the single authoritative integration release identity."""
    try:
        manifest = json.loads(
            Path(__file__).with_name("manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, TypeError, ValueError):
        return "unknown"
    return str(manifest.get("version") or "unknown")


INTEGRATION_VERSION = _integration_version()


class KEMSEntity(CoordinatorEntity):
    """Base class for coordinator-backed KEMS entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KEMSCoordinator, key: str) -> None:
        """Initialise a KEMS entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=NAME,
            manufacturer="KEMS",
            model="Whole-home proposal simulation",
            sw_version=INTEGRATION_VERSION,
        )
