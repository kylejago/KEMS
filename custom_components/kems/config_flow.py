"""Config and options flows for KEMS."""

from __future__ import annotations

from typing import Any, Literal

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
    selector,
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
    CONF_CONTROL_ENABLED,
    CONF_CURRENT_EXPORT_RATE,
    CONF_CURRENT_IMPORT_RATE,
    CONF_DISCHARGE_EFFICIENCY,
    CONF_DISCOUNT_RATE,
    CONF_ELECTRICITY_INFLATION,
    CONF_ELECTRICITY_STANDING_CHARGE,
    CONF_EMERGENCY_STOP,
    CONF_EPS_CRITICAL_PERCENT,
    CONF_EPS_LIMIT,
    CONF_EPS_WARNING_PERCENT,
    CONF_EV_CHARGING,
    CONF_EV_CONNECTED,
    CONF_EV_POWER,
    CONF_EV_SOC,
    CONF_EV_STATUS,
    CONF_EXPORT_LIMIT,
    CONF_EXPORT_RATE,
    CONF_EXPORT_TARIFF_STATUS,
    CONF_FORECAST_ENABLED,
    CONF_FORECAST_OPEN_METEO_ENABLED,
    CONF_FORECAST_OPEN_METEO_REFRESH_MINUTES,
    CONF_FORECAST_PERFORMANCE_RATIO,
    CONF_FORECAST_RECOVERY_MARGIN_KWH,
    CONF_FORECAST_RESERVE_SAFETY_MARGIN_PERCENT,
    CONF_FORECAST_WATCH_MARGIN_KWH,
    CONF_GAS_COST_TODAY,
    CONF_GAS_CURRENT_RATE,
    CONF_GAS_KWH_PER_M3,
    CONF_GAS_METER_TOTAL,
    CONF_GAS_STANDING_CHARGE,
    CONF_GAS_USAGE_TODAY,
    CONF_GRANTS_REBATES,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_GRID_STABILITY_SECONDS,
    CONF_HISTORY_DAYS,
    CONF_HOUSE_LOAD,
    CONF_INTELLIGENT_SLOT,
    CONF_INVERTER_LIMIT,
    CONF_ISLAND_RESERVE_PERCENT,
    CONF_MANUAL_DAY_RATE,
    CONF_MANUAL_OFFPEAK_END,
    CONF_MANUAL_OFFPEAK_RATE,
    CONF_MANUAL_OFFPEAK_START,
    CONF_MANUAL_STANDING_CHARGE,
    CONF_MANUAL_SYSTEM_COSTS,
    CONF_MAX_CHARGE,
    CONF_MAX_DISCHARGE,
    CONF_NEXT_IMPORT_RATE,
    CONF_NEXT_OFFPEAK_START,
    CONF_OFF_PEAK,
    CONF_OFFPEAK_END,
    CONF_OPERATING_MODE,
    CONF_PROPOSAL_SOLAR_ENABLED,
    CONF_PROPOSAL_SOLAR_FACTOR,
    CONF_ROI_FORECAST_YEARS,
    CONF_SAVING_SESSION_ENABLED,
    CONF_SAVING_SESSION_EVENTS,
    CONF_SAVING_SESSION_EXPORT_BASELINE,
    CONF_SAVING_SESSION_IMPORT_BASELINE,
    CONF_SCAN_INTERVAL,
    CONF_SIMULATION_STRATEGY,
    CONF_SITE_IMPORT_LIMIT,
    CONF_SOLAR_POWER,
    CONF_STALE_DATA_SECONDS,
    CONF_SYSTEM_COMMISSIONED,
    CONF_SYSTEM_COST,
    CONF_SYSTEM_TYPE,
    CONF_TARIFF_MODE,
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
from .product_types import SYSTEM_TYPE_DEFINITIONS, SYSTEM_TYPES

SENSOR_SELECTOR = EntitySelector(EntitySelectorConfig(domain="sensor"))
BINARY_SENSOR_SELECTOR = EntitySelector(EntitySelectorConfig(domain="binary_sensor"))
EVENT_SELECTOR = EntitySelector(EntitySelectorConfig(domain="event"))

BINARY_KEYS = {
    CONF_OFF_PEAK,
    CONF_INTELLIGENT_SLOT,
    CONF_EV_CONNECTED,
    CONF_EV_CHARGING,
}


def _number(
    minimum: float,
    maximum: float,
    step: float | Literal["any"],
    unit: str | None = None,
):
    """Return a boxed Home Assistant number selector."""
    config: dict[str, Any] = {
        "min": minimum,
        "max": maximum,
        "step": step,
        "mode": "box",
    }
    if unit:
        config["unit_of_measurement"] = unit
    return selector({"number": config})


def _select(options: list[tuple[str, str]]):
    """Return a labelled dropdown selector."""
    return selector(
        {
            "select": {
                "mode": "dropdown",
                "options": [
                    {"value": value, "label": label} for value, label in options
                ],
            }
        }
    )


BOOLEAN_SELECTOR = selector({"boolean": {}})
TIME_SELECTOR = selector({"time": {}})

EXPORT_TARIFF_STATUS_SELECTOR = _select(
    [
        ("active", "Active - export is paid"),
        ("awaiting", "Not active / awaiting export tariff"),
    ]
)

TARIFF_MODE_SELECTOR = _select(
    [
        (
            "automatic",
            "Automatic from Home Assistant, with manual fallback",
        ),
        ("manual", "Always use the prices and times entered below"),
    ]
)

SYSTEM_TYPE_SELECTOR = _select(
    [(key, SYSTEM_TYPE_DEFINITIONS[key].label) for key in SYSTEM_TYPES]
)

USER_MODE_SELECTOR = _select(
    [
        ("observe", "Live"),
        ("simulate", "Simulate"),
        ("control", "Control"),
    ]
)


def _entity_schema(
    suggested: dict[str, Any],
    *,
    require_import_rate: bool,
) -> vol.Schema:
    """Build the manual entity-review form with discovered suggestions."""
    schema: dict[vol.Marker, Any] = {}
    for key in ENTITY_MAPPING_KEYS:
        if key == CONF_SAVING_SESSION_EVENTS:
            entity_selector = EVENT_SELECTOR
        else:
            entity_selector = (
                BINARY_SENSOR_SELECTOR if key in BINARY_KEYS else SENSOR_SELECTOR
            )
        default = suggested.get(key)
        required = key == CONF_CURRENT_IMPORT_RATE and require_import_rate
        if required:
            marker = (
                vol.Required(key, default=default) if default else vol.Required(key)
            )
        else:
            marker = (
                vol.Optional(key, default=default) if default else vol.Optional(key)
            )
        schema[marker] = entity_selector
    return vol.Schema(schema)


MANUAL_TARIFF_FIELDS = {
    vol.Required(CONF_MANUAL_DAY_RATE): _number(0, 200, "any", "p/kWh"),
    vol.Required(CONF_MANUAL_OFFPEAK_RATE): _number(0, 200, "any", "p/kWh"),
    vol.Required(CONF_MANUAL_STANDING_CHARGE): _number(0, 500, "any", "p/day"),
    vol.Required(CONF_EXPORT_TARIFF_STATUS): EXPORT_TARIFF_STATUS_SELECTOR,
    vol.Required(CONF_EXPORT_RATE): _number(0, 200, 0.01, "p/kWh"),
    vol.Required(CONF_MANUAL_OFFPEAK_START): TIME_SELECTOR,
    vol.Required(CONF_MANUAL_OFFPEAK_END): TIME_SELECTOR,
}
TARIFF_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TARIFF_MODE): TARIFF_MODE_SELECTOR,
        **MANUAL_TARIFF_FIELDS,
    }
)
MANUAL_TARIFF_SCHEMA = vol.Schema(MANUAL_TARIFF_FIELDS)

BATTERY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BATTERY_CAPACITY): _number(0.1, 500, 0.01, "kWh"),
        vol.Required(CONF_BATTERY_RESERVE): _number(0, 95, 0.1, "%"),
        vol.Required(CONF_BATTERY_INITIAL): _number(0, 100, 0.1, "%"),
        vol.Required(CONF_MAX_CHARGE): _number(0.1, 100, 0.1, "kW"),
        vol.Required(CONF_MAX_DISCHARGE): _number(0.1, 100, 0.1, "kW"),
        vol.Required(CONF_INVERTER_LIMIT): _number(0.1, 100, 0.1, "kW"),
        vol.Required(CONF_EXPORT_LIMIT): _number(0, 100, 0.1, "kW"),
        vol.Required(CONF_SITE_IMPORT_LIMIT): _number(0, 100, 0.1, "kW"),
        vol.Required(CONF_CHARGE_EFFICIENCY): _number(0.5, 1.0, 0.01),
        vol.Required(CONF_DISCHARGE_EFFICIENCY): _number(0.5, 1.0, 0.01),
        vol.Required(CONF_BATTERY_POWER_POSITIVE_IS_DISCHARGE): BOOLEAN_SELECTOR,
    }
)

SOLAR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PROPOSAL_SOLAR_ENABLED): BOOLEAN_SELECTOR,
        vol.Required(CONF_PROPOSAL_SOLAR_FACTOR): _number(0, 2, 0.01),
        vol.Required(CONF_BATTERY_EXPORT_ENABLED): BOOLEAN_SELECTOR,
        vol.Required(CONF_SIMULATION_STRATEGY): _select(
            [
                (
                    "paced_export",
                    "Reserve the home, then pace export to the next cheap period",
                ),
                ("self_use", "Use solar and battery for the home first"),
            ]
        ),
        vol.Required(CONF_SAVING_SESSION_ENABLED): BOOLEAN_SELECTOR,
    }
)

FORECAST_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_FORECAST_ENABLED): BOOLEAN_SELECTOR,
        vol.Required(CONF_FORECAST_OPEN_METEO_ENABLED): BOOLEAN_SELECTOR,
        vol.Required(CONF_FORECAST_OPEN_METEO_REFRESH_MINUTES): _number(
            15, 180, 1, "min"
        ),
        vol.Required(CONF_FORECAST_PERFORMANCE_RATIO): _number(0.5, 1.1, 0.01),
        vol.Required(CONF_FORECAST_RESERVE_SAFETY_MARGIN_PERCENT): _number(
            0, 30, 0.1, "%"
        ),
        vol.Required(CONF_FORECAST_WATCH_MARGIN_KWH): _number(0, 20, 0.1, "kWh"),
        vol.Required(CONF_FORECAST_RECOVERY_MARGIN_KWH): _number(0, 10, 0.1, "kWh"),
    }
)

FINANCIAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SYSTEM_COST): _number(0, 1_000_000, 1, "GBP"),
        vol.Required(CONF_ADDITIONAL_COSTS): _number(0, 1_000_000, 1, "GBP"),
        vol.Required(CONF_GRANTS_REBATES): _number(0, 1_000_000, 1, "GBP"),
        vol.Optional(CONF_COMMISSIONING_DATE): DateSelector(),
        vol.Required(CONF_ANNUAL_MAINTENANCE): _number(0, 100_000, 1, "GBP"),
        vol.Required(CONF_MANUAL_SYSTEM_COSTS): _number(0, 1_000_000, 1, "GBP"),
        vol.Required(CONF_ELECTRICITY_INFLATION): _number(-50, 100, 0.1, "%"),
        vol.Required(CONF_BATTERY_DEGRADATION): _number(0, 20, 0.1, "%"),
        vol.Required(CONF_DISCOUNT_RATE): _number(0, 100, 0.01, "%"),
        vol.Required(CONF_ROI_FORECAST_YEARS): _number(1, 40, 1, "years"),
    }
)

MONITORING_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCAN_INTERVAL): _number(30, 3600, 1, "seconds"),
        vol.Required(CONF_HISTORY_DAYS): _number(1, 365, 1, "days"),
        vol.Required(CONF_GAS_KWH_PER_M3): _number(1, 20, "any", "kWh/m³"),
    }
)

CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SYSTEM_TYPE): SYSTEM_TYPE_SELECTOR,
        vol.Required(CONF_OPERATING_MODE): USER_MODE_SELECTOR,
        vol.Required(CONF_CONTROL_ENABLED): BOOLEAN_SELECTOR,
        vol.Required(CONF_SYSTEM_COMMISSIONED): BOOLEAN_SELECTOR,
        vol.Required(CONF_EMERGENCY_STOP): BOOLEAN_SELECTOR,
        vol.Required(CONF_STALE_DATA_SECONDS): _number(30, 3600, 1, "seconds"),
        vol.Required(CONF_GRID_STABILITY_SECONDS): _number(30, 1800, 1, "seconds"),
        vol.Required(CONF_EPS_LIMIT): _number(0.1, 100, 0.1, "kW"),
        vol.Required(CONF_EPS_WARNING_PERCENT): _number(1, 99, 0.1, "%"),
        vol.Required(CONF_EPS_CRITICAL_PERCENT): _number(2, 100, 0.1, "%"),
        vol.Required(CONF_ISLAND_RESERVE_PERCENT): _number(0, 95, 0.1, "%"),
    }
)


class KEMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle automatic and manual KEMS setup."""

    VERSION = 13
    MINOR_VERSION = 0

    def __init__(self) -> None:
        """Initialise the flow state."""
        self._discovery = DiscoveryResult({}, {}, ())
        self._suggested: dict[str, Any] = {}
        self._initial_options: dict[str, Any] = dict(DEFAULT_OPTIONS)

    def _create_entry(self, data: dict[str, Any]):
        """Create KEMS with complete mutable defaults."""
        return self.async_create_entry(
            title=NAME,
            data=data,
            options=self._initial_options,
        )

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
        """Choose automatic or manual tariff setup and confirm discovery."""
        if user_input is not None:
            mode = str(user_input[CONF_TARIFF_MODE])
            self._initial_options[CONF_TARIFF_MODE] = mode
            if user_input.get("review_entities"):
                return await self.async_step_entities()
            if mode == "manual":
                return await self.async_step_manual_tariff()
            if CONF_CURRENT_IMPORT_RATE not in self._suggested:
                return await self.async_step_entities()
            return self._create_entry(self._suggested)

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
                {
                    vol.Required(
                        CONF_TARIFF_MODE,
                        default=DEFAULT_OPTIONS[CONF_TARIFF_MODE],
                    ): TARIFF_MODE_SELECTOR,
                    vol.Optional("review_entities", default=False): BOOLEAN_SELECTOR,
                }
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
        manual = self._initial_options[CONF_TARIFF_MODE] == "manual"
        if user_input is not None:
            cleaned = {key: value for key, value in user_input.items() if value}
            validation = await async_validate_entity_mappings(self.hass, cleaned)
            missing_required = (
                not manual and CONF_CURRENT_IMPORT_RATE not in validation.accepted
            )
            if validation.rejected or missing_required:
                errors["base"] = "invalid_source_mapping"
                self._suggested = cleaned
            else:
                self._suggested = dict(validation.accepted)
                if manual:
                    return await self.async_step_manual_tariff()
                return self._create_entry(self._suggested)
        return self.async_show_form(
            step_id="entities",
            data_schema=_entity_schema(
                self._suggested,
                require_import_rate=not manual,
            ),
            errors=errors,
        )

    async def async_step_manual_tariff(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Collect manual tariff prices and cheap-period times during setup."""
        if user_input is not None:
            self._initial_options.update(user_input)
            self._initial_options[CONF_TARIFF_MODE] = "manual"
            return self._create_entry(self._suggested)
        suggested = dict(DEFAULT_OPTIONS)
        suggested[CONF_TARIFF_MODE] = "manual"
        return self.async_show_form(
            step_id="manual_tariff",
            data_schema=self.add_suggested_values_to_schema(
                MANUAL_TARIFF_SCHEMA,
                suggested,
            ),
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
                {vol.Optional("review_entities", default=False): BOOLEAN_SELECTOR}
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
        tariff_mode = str(
            entry.options.get(
                CONF_TARIFF_MODE,
                DEFAULT_OPTIONS[CONF_TARIFF_MODE],
            )
        )
        require_import_rate = tariff_mode != "manual"
        if user_input is not None:
            cleaned = {key: value for key, value in user_input.items() if value}
            validation = await async_validate_entity_mappings(self.hass, cleaned)
            missing_required = (
                require_import_rate
                and CONF_CURRENT_IMPORT_RATE not in validation.accepted
            )
            if validation.rejected or missing_required:
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
            data_schema=_entity_schema(
                self._suggested,
                require_import_rate=require_import_rate,
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Return the KEMS options flow."""
        return KEMSOptionsFlow()


class KEMSOptionsFlow(OptionsFlowWithReload):
    """Present KEMS settings as a friendly category menu."""

    MENU_OPTIONS = {
        "tariff": "Tariff and prices",
        "battery": "Battery, inverter and grid limits",
        "solar": "Solar and export",
        "forecast": "Forecast and reserve planning",
        "financial": "System cost and ROI",
        "monitoring": "Monitoring and history",
        "control": "KEMS type, mode and safety",
    }

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Show the KEMS settings menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=self.MENU_OPTIONS,
        )

    def _suggested_options(self) -> dict[str, Any]:
        """Return complete options with safe defaults."""
        values = {**DEFAULT_OPTIONS, **dict(self.config_entry.options)}
        if not values.get(CONF_COMMISSIONING_DATE):
            values.pop(CONF_COMMISSIONING_DATE, None)
        # Shadow remains an engineering mode but is intentionally not a user
        # choice. Existing shadow installs show as Simulate in the normal UI.
        if values.get(CONF_OPERATING_MODE) == "shadow":
            values[CONF_OPERATING_MODE] = "simulate"
        return values

    def _save_options(self, user_input: dict[str, Any]):
        """Merge one category without losing settings from other pages."""
        options = {
            **DEFAULT_OPTIONS,
            **dict(self.config_entry.options),
            **user_input,
        }
        if not options.get(CONF_COMMISSIONING_DATE):
            options.pop(CONF_COMMISSIONING_DATE, None)
        if options.get(CONF_SYSTEM_TYPE) == "live_data":
            options[CONF_OPERATING_MODE] = "observe"
        return self.async_create_entry(data=options)

    def _show_category(self, step_id: str, schema: vol.Schema):
        """Show a category form with current values prefilled."""
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                schema,
                self._suggested_options(),
            ),
        )

    async def async_step_tariff(self, user_input: dict[str, Any] | None = None):
        """Configure import/export prices and cheap-period times."""
        if user_input is not None:
            return self._save_options(user_input)
        return self._show_category("tariff", TARIFF_SCHEMA)

    async def async_step_battery(self, user_input: dict[str, Any] | None = None):
        """Configure battery, inverter and site limits."""
        if user_input is not None:
            return self._save_options(user_input)
        return self._show_category("battery", BATTERY_SCHEMA)

    async def async_step_solar(self, user_input: dict[str, Any] | None = None):
        """Configure solar and export simulation behaviour."""
        if user_input is not None:
            return self._save_options(user_input)
        return self._show_category("solar", SOLAR_SCHEMA)

    async def async_step_forecast(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Configure Full KEMS Forecast and reserve planning."""
        if user_input is not None:
            return self._save_options(user_input)
        return self._show_category("forecast", FORECAST_SCHEMA)

    async def async_step_financial(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Configure system costs and ROI assumptions."""
        if user_input is not None:
            return self._save_options(user_input)
        return self._show_category("financial", FINANCIAL_SCHEMA)

    async def async_step_monitoring(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Configure refresh, retention and gas conversion."""
        if user_input is not None:
            return self._save_options(user_input)
        return self._show_category("monitoring", MONITORING_SCHEMA)

    async def async_step_control(self, user_input: dict[str, Any] | None = None):
        """Configure the KEMS type, simple mode and safety safeguards."""
        if user_input is not None:
            return self._save_options(user_input)
        return self._show_category("control", CONTROL_SCHEMA)
