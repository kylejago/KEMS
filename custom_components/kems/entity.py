"""Base entity for KEMS."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME, VERSION
from .coordinator import KEMSCoordinator


class KEMSEntity(CoordinatorEntity[KEMSCoordinator]):
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
            model="Energy Management System",
            sw_version=VERSION,
        )
