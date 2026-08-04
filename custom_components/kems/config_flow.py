"""Config and options flows for KEMS."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
)

from .const import (
    CONF_ADDITIONAL_COSTS,
    CONF_ANNUAL_MAINTENANCE,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_CURRENT,
    CONF_BATTERY_DEGRADATION,
    CONF_BATTERY_EXPORT_ENABLED,
    CONF_BATTERY_INITIAL,
    CONF_BATTERY_POWER,
    CONF_BATTERY_POWER_POSITIVE_IS_DISCHARGE,
    CONF_BATTERY_RESERVE,
    CONF_BATTERY_SOC,
    CONF_BATTERY_VOLTAGE,
    CONF_CHARGE_EFFICIENCY,
    CONF_COMMISSIONING_DATE,
    CONF_CURRENT_EXPORT_RATE,
    CONF_CURRENT_IMPORT_RATE,
    CONF_DISCHARGE_EFFICIENCY,
    CONF_DISCOUNT_RATE,
    CONF_ELECTRICITY_INFLATION,
    CONF_ELECTRICITY_STANDING_CHARGE,
    CONF_EV_CHARGING,
    CONF_EV_CONNECTED,
    CONF_EV_POWER,
    CONF_EV_SOC,
    CONF_EV_STATUS,
    CONF_EXPORT_LIMIT,
    CONF_EXPORT_RATE,
    CONF_GAS_COST_TODAY,
    CONF_GAS_CURRENT_RATE,
    CONF_GAS_KWH_PER_M3,
    CONF_GAS_METER_TOTAL,
    CONF_GAS_STANDING_CHARGE,
    CONF_GAS_USAGE_TODAY,
    CONF_GRANTS_REBATES,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_HISTORY_DAYS,
    CONF_HOUSE_LOAD,
    CONF_INTELLIGENT_SLOT,
    CONF_INVERTER_LIMIT,
    CONF_MANUAL_SYSTEM_COSTS,
    CONF_MAX_CHARGE,
    CONF_MAX_DISCHARGE,
    CONF_NEXT_IMPORT_RATE,
    CONF_NEXT_OFFPEAK_START,
    CONF_OFF_PEAK,
    CONF_OFFPEAK_END,
    CONF_PROPOSAL_SOLAR_ENABLED,
    CONF_PROPOSAL_SOLAR_FACTOR,
    CONF_ROI_FORECAST_YEARS,
    CONF_SAVING_SESSION_ENABLED,
    CONF_SAVING_SESSION_EVENTS,
    CONF_SAVING_SESSION_EXPORT_BASELINE,
    CONF_SAVING_SESSION_IMPORT_BASELINE,
    CONF_SCAN_INTERVAL,
    CONF_SIMULATION_STRATEGY,
    CONF_SOLAR_POWER,
    CONF_SYSTEM_COST,
    DEFAULT_OPTIONS,
    DOMAIN,
    ENTITY_MAPPING_KEYS,
    NAME,
)
from .entity_discovery import (
    DiscoveryResult,
    async_discover_entities,
    async_validate_entity_mappings,
)

SENSOR_SELECTOR = EntitySelector(EntitySelectorConfig(domain="sensor"))
BINARY_SENSOR_SELECTOR = EntitySelector(EntitySelectorConfig(domain="binary_sensor"))
EVENT_SELECTOR = EntitySelector(EntitySelectorConfig(domain="event"))

BINARY_KEYS = {
    CONF_OFF_PEAK,
    CONF_INTELLIGENT_SLOT,
    CONF_EV_CONNECTED,
    CONF_EV_CHARGING,
}


def _entity_schema(suggested: dict[str, Any]) -> vol.Schema:
    """Build the manual entity-review form with discovered suggestions."""
    schema: dict[vol.Marker, Any] = {}
    for key in ENTITY_MAPPING_KEYS:
        if key == CONF_SAVING_SESSION_EVENTS:
            selector = EVENT_SELECTOR
        else:
            selector = BINARY_SENSOR_SELECTOR if key in BINARY_KEYS else SENSOR_SELECTOR
        default = suggested.get(key)
        if key == CONF_CURRENT_IMPORT_RATE:
            marker = (
                vol.Required(key, default=default) if default else vol.Required(key)
            )
        else:
            marker = (
                vol.Optional(key, default=default) if default else vol.Optional(key)
            )
        schema[marker] = selector
    return vol.Schema(schema)


OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=30, max=3600)
        ),
        vol.Required(CONF_HISTORY_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=365)
        ),
        vol.Required(CONF_BATTERY_CAPACITY): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=500)
        ),
        vol.Required(CONF_BATTERY_RESERVE): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=95)
        ),
        vol.Required(CONF_BATTERY_INITIAL): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
        vol.Required(CONF_MAX_CHARGE): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=100)
        ),
        vol.Required(CONF_MAX_DISCHARGE): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=100)
        ),
        vol.Required(CONF_CHARGE_EFFICIENCY): vol.All(
            vol.Coerce(float), vol.Range(min=0.5, max=1.0)
        ),
        vol.Required(CONF_DISCHARGE_EFFICIENCY): vol.All(
            vol.Coerce(float), vol.Range(min=0.5, max=1.0)
        ),
        vol.Required(CONF_EXPORT_RATE): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=200)
        ),
        vol.Required(CONF_INVERTER_LIMIT): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=100)
        ),
        vol.Required(CONF_EXPORT_LIMIT): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
        vol.Required(CONF_BATTERY_EXPORT_ENABLED): bool,
        vol.Required(CONF_SAVING_SESSION_ENABLED): bool,
        vol.Required(CONF_PROPOSAL_SOLAR_ENABLED): bool,
        vol.Required(CONF_PROPOSAL_SOLAR_FACTOR): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=2)
        ),
        vol.Required(CONF_GAS_KWH_PER_M3): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=20)
        ),
        vol.Required(CONF_BATTERY_POWER_POSITIVE_IS_DISCHARGE): bool,
        vol.Required(CONF_SYSTEM_COST): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1000000)
        ),
        vol.Required(CONF_ADDITIONAL_COSTS): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1000000)
        ),
        vol.Required(CONF_GRANTS_REBATES): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1000000)
        ),
        vol.Optional(CONF_COMMISSIONING_DATE): DateSelector(),
        vol.Required(CONF_ANNUAL_MAINTENANCE): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100000)
        ),
        vol.Required(CONF_MANUAL_SYSTEM_COSTS): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=1000000)
        ),
        vol.Required(CONF_ELECTRICITY_INFLATION): vol.All(
            vol.Coerce(float), vol.Range(min=-50, max=100)
        ),
        vol.Required(CONF_BATTERY_DEGRADATION): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=20)
        ),
        vol.Required(CONF_DISCOUNT_RATE): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
        vol.Required(CONF_ROI_FORECAST_YEARS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=40)
        ),
        vol.Required(CONF_SIMULATION_STRATEGY): vol.In(
            {
                "paced_export": "Pace battery export until next cheap period",
                "self_use": "Solar self-use first",
            }
        ),
    }
)


class KEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle automatic and manual KEMS setup."""

    VERSION = 9
    MINOR_VERSION = 0

    def __init__(self) -> None:
        """Initialise the flow state."""
        self._discovery = DiscoveryResult({}, {}, ())
        self._suggested: dict[str, Any] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Automatically scan for supported source entities."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self._discovery = await async_discover_entities(self.hass)
        self._suggested = dict(self._discovery.mappings)
        return await self.async_step_confirm(user_input)

    async def async_step_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Confirm automatic discovery or open manual review."""
        if user_input is not None:
            if user_input.get("review_entities"):
                return await self.async_step_entities()
            if CONF_CURRENT_IMPORT_RATE not in self._suggested:
                return await self.async_step_entities()
            return self.async_create_entry(title=NAME, data=self._suggested)

        provider_counts = {
            "electricity": sum(
                key
                in {
                    CONF_CURRENT_IMPORT_RATE,
                    CONF_NEXT_IMPORT_RATE,
                    CONF_CURRENT_EXPORT_RATE,
                    CONF_ELECTRICITY_STANDING_CHARGE,
                    CONF_OFF_PEAK,
                    CONF_INTELLIGENT_SLOT,
                    CONF_NEXT_OFFPEAK_START,
                    CONF_OFFPEAK_END,
                    CONF_SAVING_SESSION_EVENTS,
                    CONF_SAVING_SESSION_IMPORT_BASELINE,
                    CONF_SAVING_SESSION_EXPORT_BASELINE,
                }
                for key in self._suggested
            ),
            "gas": sum(
                key
                in {
                    CONF_GAS_CURRENT_RATE,
                    CONF_GAS_STANDING_CHARGE,
                    CONF_GAS_METER_TOTAL,
                    CONF_GAS_USAGE_TODAY,
                    CONF_GAS_COST_TODAY,
                }
                for key in self._suggested
            ),
            "ohme": sum(
                key
                in {
                    CONF_EV_STATUS,
                    CONF_EV_CONNECTED,
                    CONF_EV_CHARGING,
                    CONF_EV_POWER,
                    CONF_EV_SOC,
                }
                for key in self._suggested
            ),
            "foxess": sum(
                key
                in {
                    CONF_HOUSE_LOAD,
                    CONF_BATTERY_SOC,
                    CONF_BATTERY_POWER,
                    CONF_BATTERY_VOLTAGE,
                    CONF_BATTERY_CURRENT,
                    CONF_SOLAR_POWER,
                    CONF_GRID_IMPORT,
                    CONF_GRID_EXPORT,
                }
                for key in self._suggested
            ),
        }
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {vol.Optional("review_entities", default=False): bool}
            ),
            description_placeholders={
                "electricity_count": str(provider_counts["electricity"]),
                "gas_count": str(provider_counts["gas"]),
                "ohme_count": str(provider_counts["ohme"]),
                "foxess_count": str(provider_counts["foxess"]),
                "detected_entities": self._discovery.summary(),
                "ambiguous": ", ".join(self._discovery.ambiguous) or "None",
            },
        )

    async def async_step_entities(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Review or manually select source entities."""
        errors: dict[str, str] = {}
        if user_input is not None:
            cleaned = {key: value for key, value in user_input.items() if value}
            validation = await async_validate_entity_mappings(self.hass, cleaned)
            if (
                validation.rejected
                or CONF_CURRENT_IMPORT_RATE not in validation.accepted
            ):
                errors["base"] = "invalid_source_mapping"
                self._suggested = cleaned
            else:
                return self.async_create_entry(
                    title=NAME,
                    data=validation.accepted,
                )
        return self.async_show_form(
            step_id="entities",
            data_schema=_entity_schema(self._suggested),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Rescan supported integrations before optional manual review."""
        entry = self._get_reconfigure_entry()
        if not self._suggested:
            validation = await async_validate_entity_mappings(
                self.hass,
                dict(entry.data),
            )
            self._discovery = await async_discover_entities(self.hass)
            self._suggested = {
                **validation.accepted,
                **self._discovery.mappings,
            }

        if user_input is not None:
            if user_input.get("review_entities"):
                return await self.async_step_reconfigure_entities()
            return self.async_update_reload_and_abort(
                entry,
                data_updates=self._suggested,
                reload_even_if_entry_is_unchanged=False,
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Optional("review_entities", default=False): bool}
            ),
            description_placeholders={
                "detected_entities": self._discovery.summary(),
                "ambiguous": ", ".join(self._discovery.ambiguous) or "None",
            },
        )

    async def async_step_reconfigure_entities(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Manually review source entities only when requested."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            cleaned = {key: value for key, value in user_input.items() if value}
            validation = await async_validate_entity_mappings(self.hass, cleaned)
            if (
                validation.rejected
                or CONF_CURRENT_IMPORT_RATE not in validation.accepted
            ):
                errors["base"] = "invalid_source_mapping"
                self._suggested = cleaned
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=validation.accepted,
                    reload_even_if_entry_is_unchanged=False,
                )
        return self.async_show_form(
            step_id="reconfigure_entities",
            data_schema=_entity_schema(self._suggested),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Return the KEMS options flow."""
        return KEMSOptionsFlow()


class KEMSOptionsFlow(OptionsFlowWithReload):
    """Configure learning retention and simulation assumptions."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Manage KEMS options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        suggested = {**DEFAULT_OPTIONS, **dict(self.config_entry.options)}
        if not suggested.get(CONF_COMMISSIONING_DATE):
            suggested.pop(CONF_COMMISSIONING_DATE, None)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA,
                suggested,
            ),
        )
