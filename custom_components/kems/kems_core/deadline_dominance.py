"""Pure helpers for final Agile maximum-discharge precedence.

When the pre-cheap SOC target is physically unreachable, the deadline decision
must dominate lower-priority price/hold allocations. These helpers calculate the
maximum safe instantaneous battery path without enabling any hardware writes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MaximumDischargeTargets:
    """House-first battery targets inside the shared AC/export envelope."""

    battery_to_home_kw: float
    battery_export_kw: float
    total_discharge_kw: float


def maximum_discharge_targets(
    *,
    battery_headroom_kw: float,
    house_load_kw: float,
    solar_kw: float,
    max_discharge_kw: float,
    inverter_limit_kw: float,
    export_limit_kw: float,
    export_allowed: bool,
) -> MaximumDischargeTargets:
    """Return the maximum safe battery command, routing house demand first.

    ``battery_headroom_kw`` is the solar-aware battery AC headroom calculated by
    the canonical five-minute deadline capacity model. Solar serves the house
    first and any solar surplus consumes site export headroom before deliberate
    battery export.
    """
    battery_headroom = max(float(battery_headroom_kw), 0.0)
    house = max(float(house_load_kw), 0.0)
    solar = max(float(solar_kw), 0.0)
    max_discharge = max(float(max_discharge_kw), 0.0)
    inverter_limit = max(float(inverter_limit_kw), 0.0)
    export_limit = max(float(export_limit_kw), 0.0)

    solar_to_home = min(house, solar)
    house_battery = min(
        max(house - solar_to_home, 0.0),
        battery_headroom,
        max_discharge,
        inverter_limit,
    )

    battery_remaining = max(
        min(battery_headroom, max_discharge, inverter_limit) - house_battery,
        0.0,
    )
    solar_surplus = max(solar - solar_to_home, 0.0)
    site_export_headroom = max(export_limit - solar_surplus, 0.0)
    battery_export = (
        min(battery_remaining, site_export_headroom) if export_allowed else 0.0
    )
    total = house_battery + battery_export

    return MaximumDischargeTargets(
        battery_to_home_kw=round(house_battery, 3),
        battery_export_kw=round(battery_export, 3),
        total_discharge_kw=round(total, 3),
    )
