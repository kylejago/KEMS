"""Alpha7.48 full-battery solar spill routing for Full KEMS Agile.

The Agile optimiser already caps stored energy at physical battery capacity, but
Alpha7.30's current-routing display reconstructs its solar routing from the
proposal simulation before substituting the independent Agile rolling battery
candidate.  When those two replays have different SOCs, the display can therefore
show Solar -> Battery even though the authoritative Agile replay is already at
100% SOC.

Alpha7.48 reconciles only that final current-routing snapshot.  At an authoritative
100% Agile SOC it blocks both solar and grid charging.  Existing solar-to-home
routing is preserved and any remaining PV is exported when a paid export tariff is
active, subject to the shared inverter/export limits; otherwise it is explicitly
curtailed.  Deliberate battery discharge/export timing remains entirely owned by
the rolling Agile plan.

This is simulation/reporting-only.  Real FoxESS hardware writes remain blocked.
"""

from __future__ import annotations

import math
from typing import Any

from . import agile_alpha730_current_routing as alpha730
from . import agile_rolling_replan as rolling
from .kems_core import SimulationConfig

_EPSILON = 1e-6
_FULL_SOC_PERCENT = 100.0


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _full_battery_snapshot(self, state: dict[str, Any]) -> dict[str, Any]:
    """Remove impossible charging once the authoritative Agile SOC is full."""
    snapshot = alpha748_original_snapshot(self, state)
    if not isinstance(snapshot, dict) or not snapshot.get("available"):
        return snapshot

    config = getattr(self, "_rolling_config", None)
    if not isinstance(config, SimulationConfig):
        return snapshot

    agile_soc = rolling._current_agile_soc(state)
    if agile_soc is None or agile_soc < _FULL_SOC_PERCENT - _EPSILON:
        snapshot["full_battery_solar_routing"] = False
        return snapshot

    solar_to_battery = max(_number(snapshot.get("solar_to_battery_kw")) or 0.0, 0.0)
    grid_to_battery = max(_number(snapshot.get("grid_to_battery_kw")) or 0.0, 0.0)
    blocked_charge = solar_to_battery + grid_to_battery

    # Even when the inherited snapshot is already correct, stamp the physical
    # capacity evidence so diagnostics can prove why charge is zero at 100% SOC.
    if blocked_charge <= _EPSILON:
        snapshot.update(
            {
                "full_battery_solar_routing": True,
                "agile_soc_percent": round(agile_soc, 3),
                "battery_charge_room_kwh": 0.0,
                "full_battery_charge_blocked_kw": 0.0,
            }
        )
        return snapshot

    house = max(_number(snapshot.get("simulated_house_load_kw")) or 0.0, 0.0)
    solar = max(_number(snapshot.get("solar_power_kw")) or 0.0, 0.0)
    solar_to_home = min(
        max(_number(snapshot.get("solar_to_home_kw")) or 0.0, 0.0),
        house,
        solar,
    )
    battery_to_home = max(_number(snapshot.get("battery_to_home_kw")) or 0.0, 0.0)
    battery_export = max(_number(snapshot.get("battery_export_kw")) or 0.0, 0.0)

    inverter_limit = max(config.inverter_limit_kw, 0.0)
    export_limit = min(max(config.export_limit_kw, 0.0), inverter_limit)
    export_allowed = config.export_tariff_status == "active"

    solar_surplus = max(solar - solar_to_home, 0.0)
    export_headroom = max(export_limit - battery_export, 0.0)
    inverter_headroom = max(
        inverter_limit - solar_to_home - battery_to_home - battery_export,
        0.0,
    )
    solar_export = (
        min(solar_surplus, export_headroom, inverter_headroom)
        if export_allowed
        else 0.0
    )
    solar_curtailment = max(solar_surplus - solar_export, 0.0)

    # With no battery charging, site import is only the unsupplied house demand.
    # This also preserves cheap-period behaviour: if the inherited strategy chose
    # grid-to-home with solar_to_home=0, the house remains on grid and PV exports.
    grid_import = max(house - solar_to_home - battery_to_home, 0.0)
    grid_export = solar_export + battery_export
    total_discharge = battery_to_home + battery_export
    kh7_ac_output = solar_to_home + solar_export + total_discharge

    previous_solar_export = max(
        _number(snapshot.get("solar_export_kw")) or 0.0,
        0.0,
    )
    snapshot.update(
        {
            "routing_basis": (
                "current coordinator routing snapshot — full-battery capacity guard"
            ),
            "solar_to_battery_kw": 0.0,
            "grid_to_battery_kw": 0.0,
            "solar_export_kw": round(solar_export, 3),
            "grid_import_kw": round(grid_import, 3),
            "grid_export_kw": round(grid_export, 3),
            "total_discharge_kw": round(total_discharge, 3),
            "normalised_kh7_ac_output_kw": round(kh7_ac_output, 3),
            "solar_curtailment_kw": round(solar_curtailment, 3),
            "solar_routing_basis": (
                "battery full: preserve solar-to-home, export remaining PV within "
                "inverter/export limits"
                if export_allowed
                else "battery full: preserve solar-to-home and curtail surplus PV; "
                "no paid export tariff active"
            ),
            "full_battery_solar_routing": True,
            "agile_soc_percent": round(agile_soc, 3),
            "battery_charge_room_kwh": 0.0,
            "full_battery_charge_blocked_kw": round(blocked_charge, 3),
            "full_battery_solar_spill_to_export_kw": round(
                max(solar_export - previous_solar_export, 0.0),
                3,
            ),
            "hardware_writes": "blocked",
        }
    )
    return snapshot


def install_alpha748_full_battery_solar_patch() -> None:
    """Install final full-SOC routing reconciliation after prior Agile patches."""
    current_snapshot = alpha730._snapshot
    if getattr(current_snapshot, "_kems_alpha748_full_battery_solar", False):
        return

    global alpha748_original_snapshot
    alpha748_original_snapshot = current_snapshot
    _full_battery_snapshot._kems_alpha748_full_battery_solar = True
    alpha730._snapshot = _full_battery_snapshot
