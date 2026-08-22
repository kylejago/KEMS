"""Project Full KEMS Agile through the existing simulated KEMS sensor contract.

The property web application intentionally consumes the stable
``sensor.kems_simulated_*`` interface.  Full KEMS Agile has a separate,
settlement-aware replay and current-routing ledger, so exposing the base proposal
``SimulationState`` through those same presentation sensors can make the web
page disagree with the Agile panel and plan.

This module fixes that boundary without replacing or mutating ``SimulationState``.
Control, ROI, lifetime accounting, commissioning and shadow safety continue to
use their existing objects.  Only the values returned by generic KEMS sensor
entities are projected from the Agile ledger while the selected system type is
Full KEMS Agile.

Release versions identify repository states, not implementation filenames.  This
module therefore has a functional canonical name and must not be copied into a
version-named Alpha8 patch chain.
"""

from __future__ import annotations

import math
from typing import Any

from .product_types import SYSTEM_TYPE_FULL_KEMS_AGILE

_MISSING = object()
_PRESENTATION_KEYS = frozenset(
    {
        "simulated_cost_today",
        "simulated_grid_import_today",
        "simulated_grid_export_today",
        "simulated_export_income_today",
        "simulated_solar_generation_today",
        "simulated_solar_curtailed_today",
        "simulated_battery_charge_today",
        "simulated_battery_to_home_today",
        "simulated_battery_export_today",
        "simulated_battery_soc",
        "simulated_house_load_power",
        "simulated_solar_power",
        "simulated_grid_import_power",
        "simulated_grid_export_power",
        "simulated_grid_net_power",
        "simulated_battery_power",
        "simulated_solar_to_battery_power",
        "simulated_battery_to_home_power",
        "simulated_battery_export_power",
        "simulated_battery_charging_power",
        "simulated_grid_bypass_power",
        "simulated_total_site_import",
        "simulated_total_kh7_ac_output",
        "target_battery_export_power",
        "exportable_battery_energy",
        "battery_energy_reserved_for_home",
        "simulation_export_rate",
    }
)


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _agile_state(coordinator: Any) -> dict[str, Any]:
    """Return the retained Agile state without reaching into HA state storage."""
    state = getattr(coordinator, "agile_smart_export_state", None)
    return state if isinstance(state, dict) else {}


def _today(state: dict[str, Any]) -> dict[str, Any]:
    periods = _dict(state.get("periods"))
    period = _dict(periods.get("today"))
    return _dict(period.get("agile_smart_export"))


def _routing(state: dict[str, Any]) -> dict[str, Any]:
    routing = _dict(state.get("current_routing_snapshot"))
    return routing if routing.get("available") else {}


def _rolling(state: dict[str, Any]) -> dict[str, Any]:
    return _dict(state.get("rolling_export_plan"))


def _sum_available(*values: Any) -> float | None:
    numbers = [_number(value) for value in values]
    if not any(value is not None for value in numbers):
        return None
    return sum(value or 0.0 for value in numbers)


def _projected_value(coordinator: Any, key: str) -> object:
    """Return one Agile presentation value or ``_MISSING`` for base behaviour."""
    settings = getattr(coordinator, "settings", None)
    if getattr(settings, "system_type", None) != SYSTEM_TYPE_FULL_KEMS_AGILE:
        return _MISSING
    if key not in _PRESENTATION_KEYS:
        return _MISSING

    state = _agile_state(coordinator)
    if not state:
        return _MISSING
    today = _today(state)
    routing = _routing(state)
    rolling = _rolling(state)

    if key == "simulated_cost_today":
        value = _number(today.get("energy_net_cost_pence"))
        return _MISSING if value is None else round(value, 2)
    if key == "simulated_grid_import_today":
        value = _number(today.get("grid_import_kwh"))
        return _MISSING if value is None else round(value, 3)
    if key == "simulated_grid_export_today":
        value = _number(today.get("grid_export_kwh"))
        return _MISSING if value is None else round(value, 3)
    if key == "simulated_export_income_today":
        value = _number(today.get("export_income_pence"))
        return _MISSING if value is None else round(value, 2)
    if key == "simulated_solar_generation_today":
        value = _number(today.get("solar_generation_kwh"))
        return _MISSING if value is None else round(value, 3)
    if key == "simulated_solar_curtailed_today":
        value = _number(today.get("solar_curtailed_kwh"))
        return _MISSING if value is None else round(value, 3)
    if key == "simulated_battery_charge_today":
        value = _sum_available(
            today.get("solar_to_battery_kwh"),
            today.get("grid_to_battery_kwh"),
        )
        return _MISSING if value is None else round(value, 3)
    if key == "simulated_battery_to_home_today":
        value = _number(today.get("battery_to_home_kwh"))
        return _MISSING if value is None else round(value, 3)
    if key == "simulated_battery_export_today":
        value = _number(today.get("battery_export_kwh"))
        return _MISSING if value is None else round(value, 3)
    if key == "simulated_battery_soc":
        value = _number(routing.get("simulated_soc_percent"))
        if value is None:
            value = _number(today.get("ending_soc_percent"))
        return _MISSING if value is None else round(value, 1)

    if not routing:
        if key == "target_battery_export_power":
            value = _number(rolling.get("current_battery_export_target_kw"))
            return _MISSING if value is None else round(value, 3)
        if key == "exportable_battery_energy":
            value = _number(rolling.get("exportable_battery_energy_kwh"))
            return _MISSING if value is None else round(value, 3)
        if key == "battery_energy_reserved_for_home":
            value = _number(rolling.get("protected_house_energy_kwh"))
            return _MISSING if value is None else round(value, 3)
        if key == "simulation_export_rate":
            value = _number(state.get("current_rate_pence"))
            return _MISSING if value is None else round(value, 4)
        return _MISSING

    current_map = {
        "simulated_house_load_power": "simulated_house_load_kw",
        "simulated_solar_power": "solar_power_kw",
        "simulated_grid_import_power": "grid_import_kw",
        "simulated_grid_export_power": "grid_export_kw",
        "simulated_solar_to_battery_power": "solar_to_battery_kw",
        "simulated_battery_to_home_power": "battery_to_home_kw",
        "simulated_battery_export_power": "battery_export_kw",
        "simulated_battery_charging_power": "grid_to_battery_kw",
        "simulated_total_site_import": "grid_import_kw",
        "simulated_total_kh7_ac_output": "normalised_kh7_ac_output_kw",
    }
    if key in current_map:
        value = _number(routing.get(current_map[key]))
        return _MISSING if value is None else round(value, 3)

    if key == "simulated_grid_net_power":
        imported = _number(routing.get("grid_import_kw"))
        exported = _number(routing.get("grid_export_kw"))
        if imported is None and exported is None:
            return _MISSING
        return round((imported or 0.0) - (exported or 0.0), 3)
    if key == "simulated_battery_power":
        discharge = _number(routing.get("total_discharge_kw")) or 0.0
        charge = (_number(routing.get("solar_to_battery_kw")) or 0.0) + (
            _number(routing.get("grid_to_battery_kw")) or 0.0
        )
        return round(discharge - charge, 3)
    if key == "simulated_grid_bypass_power":
        imported = _number(routing.get("grid_import_kw"))
        grid_charge = _number(routing.get("grid_to_battery_kw"))
        if imported is None:
            return _MISSING
        return round(max(imported - (grid_charge or 0.0), 0.0), 3)
    if key == "target_battery_export_power":
        value = _number(rolling.get("current_battery_export_target_kw"))
        if value is None:
            value = _number(routing.get("battery_export_kw"))
        return _MISSING if value is None else round(value, 3)
    if key == "exportable_battery_energy":
        value = _number(rolling.get("exportable_battery_energy_kwh"))
        return _MISSING if value is None else round(value, 3)
    if key == "battery_energy_reserved_for_home":
        value = _number(rolling.get("protected_house_energy_kwh"))
        return _MISSING if value is None else round(value, 3)
    if key == "simulation_export_rate":
        value = _number(routing.get("current_agile_rate_pence"))
        if value is None:
            value = _number(state.get("current_rate_pence"))
        return _MISSING if value is None else round(value, 4)

    return _MISSING


def install_agile_simulation_presentation() -> None:
    """Install the presentation adapter before KEMS sensor entities are created."""
    from . import sensor as sensor_module

    sensor_class = sensor_module.KEMSSensor
    if getattr(sensor_class, "_kems_agile_simulation_presentation", False):
        return

    native_property = sensor_class.native_value
    attributes_property = sensor_class.extra_state_attributes
    original_native = native_property.fget
    original_attributes = attributes_property.fget
    if original_native is None or original_attributes is None:
        raise RuntimeError("KEMS sensor properties are unavailable for projection")

    def projected_native_value(self):
        projected = _projected_value(
            self.coordinator,
            self.entity_description.key,
        )
        if projected is _MISSING:
            return original_native(self)
        return projected

    def projected_attributes(self):
        attributes = original_attributes(self)
        if (
            self.entity_description.key not in _PRESENTATION_KEYS
            or getattr(self.coordinator.settings, "system_type", None)
            != SYSTEM_TYPE_FULL_KEMS_AGILE
        ):
            return attributes
        result = dict(attributes or {})
        result.update(
            {
                "presentation_source": "Full KEMS Agile settlement-aware replay",
                "presentation_system_type": SYSTEM_TYPE_FULL_KEMS_AGILE,
                "base_simulation_state_preserved": True,
                "reporting_only": True,
                "hardware_writes": "blocked",
            }
        )
        return result

    sensor_class.native_value = property(projected_native_value)
    sensor_class.extra_state_attributes = property(projected_attributes)
    sensor_class._kems_agile_simulation_presentation = True
