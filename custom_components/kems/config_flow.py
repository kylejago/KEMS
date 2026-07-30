"""Config flow for KEMS."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import (
    CONF_CURRENT_IMPORT_RATE,
    CONF_EV_CHARGING,
    CONF_EV_CONNECTED,
    CONF_EV_POWER,
    CONF_EV_SOC,
    CONF_INTELLIGENT_SLOT,
    CONF_NEXT_IMPORT_RATE,
    CONF_NEXT_OFFPEAK_START,
    CONF_OFF_PEAK,
    CONF_OFFPEAK_END,
    DOMAIN,
    NAME,
)

SENSOR_SELECTOR = EntitySelector(EntitySelectorConfig(domain="sensor"))
BINARY_SENSOR_SELECTOR = EntitySelector(EntitySelectorConfig(domain="binary_sensor"))

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CURRENT_IMPORT_RATE): SENSOR_SELECTOR,
        vol.Required(CONF_NEXT_IMPORT_RATE): SENSOR_SELECTOR,
        vol.Required(CONF_OFF_PEAK): BINARY_SENSOR_SELECTOR,
        vol.Required(CONF_INTELLIGENT_SLOT): BINARY_SENSOR_SELECTOR,
        vol.Required(CONF_NEXT_OFFPEAK_START): SENSOR_SELECTOR,
        vol.Required(CONF_OFFPEAK_END): SENSOR_SELECTOR,
        vol.Optional(CONF_EV_CONNECTED): BINARY_SENSOR_SELECTOR,
        vol.Optional(CONF_EV_CHARGING): BINARY_SENSOR_SELECTOR,
        vol.Optional(CONF_EV_POWER): SENSOR_SELECTOR,
        vol.Optional(CONF_EV_SOC): SENSOR_SELECTOR,
    }
)


class KEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the KEMS config flow."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Configure KEMS source entities."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=NAME, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
        )
