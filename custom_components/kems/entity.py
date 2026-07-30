"""Base entity for KEMS."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import KEMSCoordinator


class KEMSEntity(CoordinatorEntity[KEMSCoordinator]):
    """Base KEMS entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KEMSCoordinator,
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
