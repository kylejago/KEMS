"""Presentation-only per-slot energy-flow contract for KEMS.

The optimiser and settlement layers remain authoritative for routing and
accounting.  This module only turns their final energy components into one
stable customer-facing shape that Home Assistant and KEMS Web can render.
"""

from __future__ import annotations

import math
from typing import Any

_EPSILON = 0.0005


def _number(value: Any) -> float | None:
    """Return a finite non-negative float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(number, 0.0)


def _route_label(routes: tuple[tuple[str, float | None], ...]) -> str:
    """Join non-zero routes using the compact dashboard vocabulary."""
    labels = [label for label, value in routes if (value or 0.0) > _EPSILON]
    if not labels:
        return "IDLE"
    if labels == ["EXPO"]:
        return "EXPORT"
    return "/".join(labels)


def build_slot_flow(
    *,
    grid_import_kwh: float | None,
    solar_generation_kwh: float | None,
    solar_to_home_kwh: float | None,
    solar_to_battery_kwh: float | None,
    solar_export_kwh: float | None,
    grid_to_battery_kwh: float | None,
    battery_to_home_kwh: float | None,
    battery_export_kwh: float | None,
    estimated_soc_percent: float | None,
    basis: str,
    scope: str = "full slot",
) -> dict[str, Any]:
    """Return one reconciled Grid/Solar/Battery presentation record.

    Grid export is always reconstructed from its two physical sources so a
    stale historical ``grid_export_kwh`` field cannot disagree with the final
    solar and battery allocations.  Solar total is source-side generation.
    Battery charge is stored energy; battery home/export are AC energy delivered.
    ``battery_kwh`` is therefore an activity total when a rare mixed-direction
    slot contains both charging and discharging.
    """
    grid_import = _number(grid_import_kwh) or 0.0
    solar_generation = _number(solar_generation_kwh)
    solar_home = _number(solar_to_home_kwh) or 0.0
    solar_battery = _number(solar_to_battery_kwh) or 0.0
    solar_export = _number(solar_export_kwh) or 0.0
    grid_battery = _number(grid_to_battery_kwh) or 0.0
    battery_home = _number(battery_to_home_kwh) or 0.0
    battery_export = _number(battery_export_kwh) or 0.0

    grid_export = solar_export + battery_export
    battery_charge = solar_battery + grid_battery
    if solar_generation is None:
        # This fallback is only for older retained rows where KEMS did not keep
        # source-side generation. New/current rows publish the real source sum.
        solar_generation = solar_home + solar_export
        if solar_battery > _EPSILON:
            solar_generation += solar_battery

    grid_action = _route_label((("IMPORT", grid_import), ("EXPO", grid_export)))
    solar_action = _route_label(
        (("HOME", solar_home), ("BATT", solar_battery), ("EXPO", solar_export))
    )
    battery_action = _route_label(
        (("HOME", battery_home), ("EXPO", battery_export), ("CHARGE", battery_charge))
    )

    grid_activity = grid_import + grid_export
    battery_activity = battery_home + battery_export + battery_charge
    solar_destination_total = solar_home + solar_battery + solar_export
    component_values = (
        grid_import,
        grid_export,
        solar_generation,
        solar_home,
        solar_battery,
        solar_export,
        grid_battery,
        battery_home,
        battery_export,
        battery_charge,
    )

    return {
        "flow_basis": basis,
        "flow_scope": scope,
        "flow_estimated_soc_percent": (
            round(float(estimated_soc_percent), 1)
            if _number(estimated_soc_percent) is not None
            else None
        ),
        "flow_grid_action": grid_action,
        "flow_grid_kwh": round(grid_activity, 3),
        "flow_grid_import_kwh": round(grid_import, 3),
        "flow_grid_export_kwh": round(grid_export, 3),
        "flow_solar_action": solar_action,
        "flow_solar_kwh": round(solar_generation, 3),
        "flow_solar_to_home_kwh": round(solar_home, 3),
        "flow_solar_to_battery_kwh": round(solar_battery, 3),
        "flow_solar_export_kwh": round(solar_export, 3),
        "flow_battery_action": battery_action,
        "flow_battery_kwh": round(battery_activity, 3),
        "flow_battery_charge_kwh": round(battery_charge, 3),
        "flow_grid_to_battery_kwh": round(grid_battery, 3),
        "flow_battery_to_home_kwh": round(battery_home, 3),
        "flow_battery_export_kwh": round(battery_export, 3),
        "flow_checks": {
            "grid_export_balance": abs(grid_export - (solar_export + battery_export))
            <= 0.002,
            "solar_destinations_within_generation": (
                solar_destination_total <= solar_generation + 0.002
            ),
            "grid_charge_within_import": grid_battery <= grid_import + 0.002,
            "components_non_negative": all(value >= 0.0 for value in component_values),
        },
    }
