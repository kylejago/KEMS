"""Date/time controls for manually selected Octopus Weekend Happy Hours."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import KEMSEntity
from .happy_hour import CONF_HAPPY_HOUR_START, parse_happy_hour_start
from .runtime_options import async_set_runtime_option


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the manual Weekend Happy Hour start control."""
    async_add_entities([KEMSWeekendHappyHourStart(entry.runtime_data)])


class KEMSWeekendHappyHourStart(KEMSEntity, DateTimeEntity):
    """Choose the start of a manually booked Weekend Happy Hour."""

    _attr_name = "Weekend Happy Hour start"
    _attr_icon = "mdi:clock-plus-outline"

    def __init__(self, coordinator) -> None:
        """Initialise the editable date/time entity."""
        super().__init__(coordinator, "weekend_happy_hour_start")
        now = datetime.now(UTC)
        self._fallback = (now + timedelta(hours=1)).replace(
            minute=0,
            second=0,
            microsecond=0,
        )

    @property
    def native_value(self) -> datetime:
        """Return the configured start or a harmless picker default."""
        configured = parse_happy_hour_start(
            self.coordinator.entry.options.get(CONF_HAPPY_HOUR_START)
        )
        return configured.astimezone(UTC) if configured is not None else self._fallback

    async def async_set_value(self, value: datetime) -> None:
        """Persist the chosen timestamp and reload KEMS atomically."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        await async_set_runtime_option(
            self.hass,
            self.coordinator.entry,
            CONF_HAPPY_HOUR_START,
            value.isoformat(),
        )
