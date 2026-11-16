"""Manual WhatsApp test buttons; no control or inverter authority."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import KEMSEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Provide independently triggered family and private WhatsApp tests."""
    coordinator = entry.runtime_data
    async_add_entities([
        KEMSWhatsAppTestButton(coordinator, private=False),
        KEMSWhatsAppTestButton(coordinator, private=True),
    ])


class KEMSWhatsAppTestButton(KEMSEntity, ButtonEntity):
    """Manually test a configured WhatsApp notification target."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, *, private: bool) -> None:
        super().__init__(
            coordinator,
            "whatsapp_private_test" if private else "whatsapp_family_test",
        )
        self._private = private
        self._attr_name = (
            "WhatsApp private test" if private else "WhatsApp family test"
        )
        self._attr_icon = "mdi:message-lock-check" if private else "mdi:message-check"

    async def async_press(self) -> None:
        """Send a fresh test on each press, without changing schedules."""
        reporter = getattr(self.coordinator, "_kems_whatsapp_reporter", None)
        if reporter is None or not reporter.enabled:
            raise HomeAssistantError("Enable WhatsApp notifications in KEMS options")
        if not await reporter.async_send_test(private=self._private):
            raise HomeAssistantError(
                "WhatsApp test failed; see KEMS WhatsApp diagnostics and notify entity"
            )
