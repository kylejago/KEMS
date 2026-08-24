"""Project Agile KEMS through the existing simulated KEMS sensor contract.

The generic ``sensor.kems_simulated_*`` interface remains stable for property
clients. Alpha8.13 no longer exposes Full KEMS Agile as a separate product; the
projection is active whenever the one KEMS product is configured for Agile
Outgoing. Other tariff strategies keep the proven base simulation values.

This is presentation-only. Control, commissioning, ROI, lifetime accounting and
real-hardware write permissions remain unchanged.
"""

from __future__ import annotations

import math
from typing import Any

from .product_types import EXPORT_TARIFF_TYPE_AGILE, export_tariff_type_from_options

_MISSING = object()
_PRESENTATION_KEYS = frozenset(
    {
        "simulated_cost_today", "simulated_grid_import_today", "simulated_grid_export_today",
        "simulated_export_income_today", "simulated_solar_generation_today",
        "simulated_solar_curtailed_today", "simulated_battery_charge_today",
        "simulated_battery_to_home_today", "simulated_battery_export_today",
        "simulated_battery_soc", "simulated_house_load_power", "simulated_solar_power",
        "simulated_grid_import_power", "simulated_grid_export_power", "simulated_grid_net_power",
        "simulated_battery_power", "simulated_solar_to_battery_power",
        "simulated_battery_to_home_power", "simulated_battery_export_power",
        "simulated_battery_charging_power", "simulated_grid_bypass_power",
        "simulated_total_site_import", "simulated_total_kh7_ac_output",
        "target_battery_export_power", "exportable_battery_energy",
        "battery_energy_reserved_for_home", "simulation_export_rate",
    }
)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _uses_agile(coordinator: Any) -> bool:
    entry = getattr(coordinator, "entry", None)
    return export_tariff_type_from_options(getattr(entry, "options", {})) == EXPORT_TARIFF_TYPE_AGILE


def _agile_state(coordinator: Any) -> dict[str, Any]:
    state = getattr(coordinator, "agile_smart_export_state", None)
    return state if isinstance(state, dict) else {}


def _today(state: dict[str, Any]) -> dict[str, Any]:
    return _dict(_dict(_dict(state.get("periods")).get("today")).get("agile_smart_export"))


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
    if not _uses_agile(coordinator) or key not in _PRESENTATION_KEYS:
        return _MISSING
    state = _agile_state(coordinator)
    if not state:
        return _MISSING
    today = _today(state)
    routing = _routing(state)
    rolling = _rolling(state)
    direct = {
        "simulated_cost_today": (today, "energy_net_cost_pence", 2),
        "simulated_grid_import_today": (today, "grid_import_kwh", 3),
        "simulated_grid_export_today": (today, "grid_export_kwh", 3),
        "simulated_export_income_today": (today, "export_income_pence", 2),
        "simulated_solar_generation_today": (today, "solar_generation_kwh", 3),
        "simulated_solar_curtailed_today": (today, "solar_curtailed_kwh", 3),
        "simulated_battery_to_home_today": (today, "battery_to_home_kwh", 3),
        "simulated_battery_export_today": (today, "battery_export_kwh", 3),
    }
    if key in direct:
        source, field, digits = direct[key]
        value = _number(source.get(field))
        return _MISSING if value is None else round(value, digits)
    if key == "simulated_battery_charge_today":
        value = _sum_available(today.get("solar_to_battery_kwh"), today.get("grid_to_battery_kwh"))
        return _MISSING if value is None else round(value, 3)
    if key == "simulated_battery_soc":
        value = _number(routing.get("simulated_soc_percent")) or _number(today.get("ending_soc_percent"))
        return _MISSING if value is None else round(value, 1)
    if not routing:
        fallback = {
            "target_battery_export_power": (rolling, "current_battery_export_target_kw", 3),
            "exportable_battery_energy": (rolling, "exportable_battery_energy_kwh", 3),
            "battery_energy_reserved_for_home": (rolling, "protected_house_energy_kwh", 3),
            "simulation_export_rate": (state, "current_rate_pence", 4),
        }
        if key in fallback:
            source, field, digits = fallback[key]
            value = _number(source.get(field))
            return _MISSING if value is None else round(value, digits)
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
        imported, exported = _number(routing.get("grid_import_kw")), _number(routing.get("grid_export_kw"))
        return _MISSING if imported is None and exported is None else round((imported or 0.0) - (exported or 0.0), 3)
    if key == "simulated_battery_power":
        discharge = _number(routing.get("total_discharge_kw")) or 0.0
        charge = (_number(routing.get("solar_to_battery_kw")) or 0.0) + (_number(routing.get("grid_to_battery_kw")) or 0.0)
        return round(discharge - charge, 3)
    if key == "simulated_grid_bypass_power":
        imported = _number(routing.get("grid_import_kw"))
        return _MISSING if imported is None else round(max(imported - (_number(routing.get("grid_to_battery_kw")) or 0.0), 0.0), 3)
    if key == "target_battery_export_power":
        value = _number(rolling.get("current_battery_export_target_kw")) or _number(routing.get("battery_export_kw"))
        return _MISSING if value is None else round(value, 3)
    if key == "exportable_battery_energy":
        value = _number(rolling.get("exportable_battery_energy_kwh"))
        return _MISSING if value is None else round(value, 3)
    if key == "battery_energy_reserved_for_home":
        value = _number(rolling.get("protected_house_energy_kwh"))
        return _MISSING if value is None else round(value, 3)
    if key == "simulation_export_rate":
        value = _number(routing.get("current_agile_rate_pence")) or _number(state.get("current_rate_pence"))
        return _MISSING if value is None else round(value, 4)
    return _MISSING


def install_agile_simulation_presentation() -> None:
    from . import sensor as sensor_module

    sensor_class = sensor_module.KEMSSensor
    if getattr(sensor_class, "_kems_agile_simulation_presentation", False):
        return
    original_native = sensor_class.native_value.fget
    original_attributes = sensor_class.extra_state_attributes.fget
    if original_native is None or original_attributes is None:
        raise RuntimeError("KEMS sensor properties are unavailable for projection")

    def projected_native_value(self):
        projected = _projected_value(self.coordinator, self.entity_description.key)
        return original_native(self) if projected is _MISSING else projected

    def projected_attributes(self):
        attributes = original_attributes(self)
        if self.entity_description.key not in _PRESENTATION_KEYS or not _uses_agile(self.coordinator):
            return attributes
        result = dict(attributes or {})
        result.update({
            "presentation_source": "KEMS Agile settlement-aware replay",
            "presentation_system_type": "kems",
            "presentation_strategy": "agile_outgoing",
            "base_simulation_state_preserved": True,
            "reporting_only": True,
            "hardware_writes": "blocked",
        })
        return result

    sensor_class.native_value = property(projected_native_value)
    sensor_class.extra_state_attributes = property(projected_attributes)
    sensor_class._kems_agile_simulation_presentation = True
