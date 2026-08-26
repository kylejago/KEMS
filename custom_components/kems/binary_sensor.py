"""Binary sensor platform for KEMS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_BATTERY_SOC,
    CONF_EV_CHARGING,
    CONF_EV_CONNECTED,
    CONF_EV_STATUS,
    CONF_GAS_COST_TODAY,
    CONF_GAS_CURRENT_RATE,
    CONF_GAS_METER_TOTAL,
    CONF_GAS_STANDING_CHARGE,
    CONF_GAS_USAGE_TODAY,
    CONF_INTELLIGENT_SLOT,
    CONF_OFF_PEAK,
)
from .entity import KEMSEntity
from .kems_core import KEMSData

IsOnFn = Callable[[KEMSData], bool | None]
GAS_SOURCE_KEYS = (
    CONF_GAS_CURRENT_RATE,
    CONF_GAS_STANDING_CHARGE,
    CONF_GAS_METER_TOTAL,
    CONF_GAS_USAGE_TODAY,
    CONF_GAS_COST_TODAY,
)


@dataclass(frozen=True, kw_only=True)
class KEMSBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describe a KEMS binary sensor."""

    is_on_fn: IsOnFn
    source_key: str | None = None
    source_any_keys: tuple[str, ...] = ()


BINARY_SENSORS: tuple[KEMSBinarySensorEntityDescription, ...] = (
    KEMSBinarySensorEntityDescription(
        key="off_peak",
        name="Off peak",
        icon="mdi:weather-night",
        source_key=CONF_OFF_PEAK,
        is_on_fn=lambda data: data.snapshot.off_peak,
    ),
    KEMSBinarySensorEntityDescription(
        key="intelligent_slot",
        name="Intelligent slot",
        icon="mdi:ev-station",
        source_key=CONF_INTELLIGENT_SLOT,
        is_on_fn=lambda data: data.snapshot.intelligent_slot,
    ),
    KEMSBinarySensorEntityDescription(
        key="intelligent_slot_source_fresh",
        name="Intelligent slot source fresh",
        icon="mdi:shield-clock-outline",
        source_key=CONF_INTELLIGENT_SLOT,
        is_on_fn=lambda data: data.snapshot.intelligent_slot_source_fresh,
    ),
    KEMSBinarySensorEntityDescription(
        key="cheap_period_confirmed",
        name="Cheap period confirmed",
        icon="mdi:cash-check",
        is_on_fn=lambda data: data.snapshot.cheap_period_confirmed,
    ),
    KEMSBinarySensorEntityDescription(
        key="ev_connected",
        name="EV connected",
        icon="mdi:ev-plug-type2",
        source_any_keys=(CONF_EV_STATUS, CONF_EV_CONNECTED),
        is_on_fn=lambda data: data.snapshot.ev_connected,
    ),
    KEMSBinarySensorEntityDescription(
        key="ev_charging",
        name="EV charging",
        icon="mdi:battery-charging",
        source_any_keys=(CONF_EV_STATUS, CONF_EV_CHARGING),
        is_on_fn=lambda data: data.snapshot.ev_charging,
    ),
    KEMSBinarySensorEntityDescription(
        key="battery_present",
        name="Battery data available",
        icon="mdi:home-battery-outline",
        source_key=CONF_BATTERY_SOC,
        is_on_fn=lambda data: data.snapshot.battery_soc is not None,
    ),
    KEMSBinarySensorEntityDescription(
        key="gas_data_available",
        name="Gas data available",
        icon="mdi:fire-check",
        source_any_keys=GAS_SOURCE_KEYS,
        is_on_fn=lambda data: data.gas.available,
    ),
    KEMSBinarySensorEntityDescription(
        key="proposal_solar_active",
        name="Proposal solar model active",
        icon="mdi:solar-power-variant-outline",
        is_on_fn=lambda data: data.simulation.proposal_solar_active,
    ),
    KEMSBinarySensorEntityDescription(
        key="export_tariff_active",
        name="Export tariff active",
        icon="mdi:cash-check",
        is_on_fn=lambda data: data.simulation.export_tariff_active,
    ),
    KEMSBinarySensorEntityDescription(
        key="no_export_mode_active",
        name="No-export mode active",
        icon="mdi:transmission-tower-off",
        is_on_fn=lambda data: data.simulation.no_export_mode_active,
    ),
    KEMSBinarySensorEntityDescription(
        key="battery_export_simulated",
        name="Battery export enabled in simulation",
        icon="mdi:battery-arrow-down-outline",
        is_on_fn=lambda data: data.simulation.battery_export_enabled,
    ),
    KEMSBinarySensorEntityDescription(
        key="battery_export_paused_for_home_reserve",
        name="Battery export paused for home reserve",
        icon="mdi:home-battery-outline",
        is_on_fn=lambda data: (data.simulation.battery_export_paused_for_home_reserve),
    ),
    KEMSBinarySensorEntityDescription(
        key="saving_session_joined",
        name="Power Down session joined",
        icon="mdi:calendar-check",
        is_on_fn=lambda data: data.simulation.saving_session_joined,
    ),
    KEMSBinarySensorEntityDescription(
        key="saving_session_active",
        name="Power Down session active",
        icon="mdi:lightning-bolt-circle",
        is_on_fn=lambda data: data.simulation.saving_session_active,
    ),
    KEMSBinarySensorEntityDescription(
        key="saving_session_baseline_incomplete",
        name="Power Down source baseline incomplete",
        icon="mdi:progress-alert",
        is_on_fn=lambda data: bool(data.simulation.saving_session_baseline_incomplete),
    ),
    KEMSBinarySensorEntityDescription(
        key="battery_reserved_for_saving_session",
        name="Battery reserved for Power Down session",
        icon="mdi:battery-lock",
        is_on_fn=lambda data: data.simulation.battery_reserved_for_saving_session,
    ),
    KEMSBinarySensorEntityDescription(
        key="battery_export_reduced_for_saving_session",
        name="Battery export reduced for Power Down session",
        icon="mdi:battery-clock-outline",
        is_on_fn=lambda data: (
            data.simulation.battery_export_reduced_for_saving_session
        ),
    ),
    KEMSBinarySensorEntityDescription(
        key="learning_ready",
        name="Learning ready",
        icon="mdi:brain",
        is_on_fn=lambda data: data.learned.ready,
    ),
    KEMSBinarySensorEntityDescription(
        key="simulation_ready",
        name="Simulation ready",
        icon="mdi:calculator-variant-outline",
        is_on_fn=lambda data: data.simulation.ready,
    ),
    KEMSBinarySensorEntityDescription(
        key="simulated_saving",
        name="Simulation shows a saving",
        icon="mdi:piggy-bank-outline",
        is_on_fn=lambda data: (
            data.simulation.saving_pence is not None
            and data.simulation.saving_pence > 0
        ),
    ),
    KEMSBinarySensorEntityDescription(
        key="roi_ready",
        name="ROI prediction ready",
        icon="mdi:finance",
        is_on_fn=lambda data: data.roi.ready,
    ),
    KEMSBinarySensorEntityDescription(
        key="system_installed",
        name="System installed",
        icon="mdi:solar-panel-large",
        is_on_fn=lambda data: data.roi.system_installed,
    ),
    KEMSBinarySensorEntityDescription(
        key="system_paid_back",
        name="System paid back",
        icon="mdi:trophy-award",
        is_on_fn=lambda data: data.roi.system_paid_back,
    ),
    KEMSBinarySensorEntityDescription(
        key="day_rate_grid_import",
        name="Grid import outside cheap period",
        icon="mdi:alert-outline",
        is_on_fn=lambda data: (
            data.snapshot.grid_import_kw is not None
            and data.snapshot.grid_import_kw > 0.1
            and not data.snapshot.cheap_period_confirmed
        ),
    ),
    KEMSBinarySensorEntityDescription(
        key="grid_available_for_control",
        name="Grid available for control",
        icon="mdi:transmission-tower",
        is_on_fn=lambda data: data.control.grid_available,
    ),
    KEMSBinarySensorEntityDescription(
        key="whole_house_island_mode",
        name="Whole-house island mode",
        icon="mdi:home-lightning-bolt",
        is_on_fn=lambda data: data.control.island_mode_active,
    ),
    KEMSBinarySensorEntityDescription(
        key="control_plan_safe",
        name="Control plan safe",
        icon="mdi:shield-check-outline",
        is_on_fn=lambda data: data.control.plan_safe,
    ),
    KEMSBinarySensorEntityDescription(
        key="control_data_fresh",
        name="Control data fresh",
        icon="mdi:database-clock",
        is_on_fn=lambda data: data.control.data_fresh,
    ),
    KEMSBinarySensorEntityDescription(
        key="kems_control_enabled",
        name="Control enabled",
        icon="mdi:toggle-switch-outline",
        is_on_fn=lambda data: data.control.control_enabled,
    ),
    KEMSBinarySensorEntityDescription(
        key="system_commissioned_for_control",
        name="System commissioned for control",
        icon="mdi:certificate-outline",
        is_on_fn=lambda data: data.control.commissioned,
    ),
    KEMSBinarySensorEntityDescription(
        key="real_control_backend_available",
        name="Real control backend available",
        icon="mdi:connection",
        is_on_fn=lambda data: data.control.real_backend_available,
    ),
    KEMSBinarySensorEntityDescription(
        key="control_commands_permitted",
        name="Control commands permitted",
        icon="mdi:send-check-outline",
        is_on_fn=lambda data: data.control.commands_permitted,
    ),
    KEMSBinarySensorEntityDescription(
        key="island_battery_conservation_active",
        name="Island battery conservation active",
        icon="mdi:battery-alert-variant-outline",
        is_on_fn=lambda data: data.control.island_battery_status
        in {"conservation", "emergency_floor"},
    ),
    KEMSBinarySensorEntityDescription(
        key="eps_load_warning",
        name="EPS load warning",
        icon="mdi:alert-outline",
        is_on_fn=lambda data: data.control.eps_warning,
    ),
    KEMSBinarySensorEntityDescription(
        key="eps_load_critical",
        name="EPS load critical",
        icon="mdi:alert-octagon-outline",
        is_on_fn=lambda data: data.control.eps_critical,
    ),
    KEMSBinarySensorEntityDescription(
        key="ev_charging_allowed_by_control",
        name="EV charging allowed by control",
        icon="mdi:ev-station",
        is_on_fn=lambda data: data.control.desired_ev_charging_allowed,
    ),
    KEMSBinarySensorEntityDescription(
        key="grid_export_allowed_by_control",
        name="Grid export allowed by control",
        icon="mdi:transmission-tower-export",
        is_on_fn=lambda data: data.control.desired_grid_export_allowed,
    ),
    KEMSBinarySensorEntityDescription(
        key="site_import_limit_exceeded",
        name="Site import limit exceeded",
        icon="mdi:transmission-tower-off",
        is_on_fn=lambda data: data.control.site_import_limit_exceeded,
    ),
    KEMSBinarySensorEntityDescription(
        key="accumulator_healthy",
        name="Accumulator healthy",
        icon="mdi:database-check-outline",
        is_on_fn=lambda data: data.lifetime.accumulator_status == "healthy",
    ),
    KEMSBinarySensorEntityDescription(
        key="historical_repair_required",
        name="Historical repair required",
        icon="mdi:database-alert-outline",
        is_on_fn=lambda data: data.lifetime.historical_repair_required,
    ),
    KEMSBinarySensorEntityDescription(
        key="last_power_down_available",
        name="Last Power Down result available",
        icon="mdi:history",
        is_on_fn=lambda data: data.last_power_down.available,
    ),
    KEMSBinarySensorEntityDescription(
        key="last_power_down_completed_successfully",
        name="Last Power Down completed successfully",
        icon="mdi:check-decagram-outline",
        is_on_fn=lambda data: data.last_power_down.completed_successfully,
    ),
    KEMSBinarySensorEntityDescription(
        key="last_power_down_ev_blocked",
        name="Last Power Down EV successfully blocked",
        icon="mdi:ev-station-off",
        is_on_fn=lambda data: data.last_power_down.ev_successfully_blocked,
    ),
)


def _source_is_configured(
    description: KEMSBinarySensorEntityDescription,
    mappings: dict[str, str],
) -> bool:
    """Return whether a binary sensor has configured source data."""
    if description.source_key is None and not description.source_any_keys:
        return True
    if description.source_key in mappings:
        return True
    return any(key in mappings for key in description.source_any_keys)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up KEMS binary sensors."""
    coordinator = entry.runtime_data
    mappings = coordinator.entities.as_dict()
    async_add_entities(
        KEMSBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
        if _source_is_configured(description, mappings)
    )


class KEMSBinarySensor(KEMSEntity, BinarySensorEntity):
    """Generic coordinator-backed KEMS binary sensor."""

    entity_description: KEMSBinarySensorEntityDescription

    def __init__(
        self,
        coordinator,
        description: KEMSBinarySensorEntityDescription,
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the binary sensor state."""
        return self.entity_description.is_on_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Explain Power Down baseline semantics without changing source truth."""
        if self.entity_description.key != "saving_session_baseline_incomplete":
            return None

        simulation = self.coordinator.data.simulation
        export_baseline_entity = self.coordinator.entities.saving_session_export_baseline
        export_baseline_mapped = bool(export_baseline_entity)
        reward_baseline_ready = simulation.saving_session_baseline_net_kwh is not None

        if not simulation.saving_session_joined:
            status = "No joined Power Down"
        elif export_baseline_mapped and not reward_baseline_ready:
            status = (
                "Export baseline mapped but unavailable — reward estimate withheld"
            )
        elif export_baseline_mapped:
            status = "Import and export baselines available — net baseline ready"
        elif reward_baseline_ready and simulation.saving_session_baseline_incomplete:
            status = (
                "Import-only baseline available — Octopus source marks calculation "
                "incomplete; no export baseline is mapped"
            )
        elif reward_baseline_ready:
            status = "Import-only baseline available — no export baseline is mapped"
        else:
            status = "Import baseline unavailable"

        return {
            "status": status,
            "reward_baseline_net_kwh": simulation.saving_session_baseline_net_kwh,
            "baseline_source": simulation.saving_session_baseline_source,
            "octopus_source_calculation_incomplete": (
                simulation.saving_session_baseline_incomplete
            ),
            "export_baseline_mapped": export_baseline_mapped,
            "export_baseline_entity_id": export_baseline_entity,
            "reward_baseline_ready": reward_baseline_ready,
            "reward_basis": (
                "import baseline minus export baseline when an export baseline is "
                "mapped; otherwise the mapped import baseline is used"
            ),
        }
