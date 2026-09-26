"""Read-only, EV-aware cheap-period routing for the no-paid-export scenario.

The configured whole-site load includes EV demand: EV is subtracted once
before allocating solar/battery to the home. No hardware command is produced
by this module. In particular, FoxESS Self Use alone is NOT proof that the
EV is supplied exclusively by grid; physical EV isolation needs a separately
commissioned, measured controller before this policy may be promoted to live.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NoExportCheapFlow:
    """Interval energies in kWh, with stored battery energy after routing."""

    grid_import_kwh: float
    grid_to_ev_kwh: float
    grid_to_home_kwh: float
    grid_to_battery_input_kwh: float
    solar_to_home_kwh: float
    solar_to_battery_input_kwh: float
    solar_curtailed_kwh: float
    battery_to_home_kwh: float
    battery_stored_kwh: float
    ev_evidence_valid: bool


def route_no_export_cheap(
    *,
    whole_site_load_kw: float,
    ev_power_kw: float | None,
    ev_charging: bool | None,
    ev_power_stale: bool,
    solar_kw: float,
    battery_stored_kwh: float,
    target_stored_kwh: float | None,
    reserve_kwh: float,
    capacity_kwh: float,
    max_charge_kw: float,
    max_discharge_kw: float,
    inverter_limit_kw: float,
    site_import_limit_kw: float | None,
    charge_efficiency: float,
    discharge_efficiency: float,
    hours: float,
) -> NoExportCheapFlow:
    """Route EV to grid, PV to home/storage, and battery ONLY to unmet home load.

    The target is a lower discharge bound, not a forced destination: excess
    stored energy is spent solely on actual home demand, never on export.
    Grid charging is allowed only for a known target shortfall. If EV power
    is missing/stale/inconsistent during charging, conservatively bypass the
    full observed load via grid and never authorise battery discharge or
    grid charge from an inferred EV/home split.
    """
    hours = max(float(hours), 0.0)
    load = max(float(whole_site_load_kw), 0.0) * hours
    solar = min(max(float(solar_kw), 0.0), max(inverter_limit_kw, 0.0)) * hours
    capacity = max(float(capacity_kwh), 0.01)
    reserve = min(max(float(reserve_kwh), 0.0), capacity)
    stored = min(max(float(battery_stored_kwh), 0.0), capacity)
    charge_eff = max(float(charge_efficiency), 0.01)
    discharge_eff = max(float(discharge_efficiency), 0.01)
    charge_budget = max(float(max_charge_kw), 0.0) * hours
    discharge_budget = max(float(max_discharge_kw), 0.0) * hours
    inverter_budget = max(float(inverter_limit_kw), 0.0) * hours

    reported_ev = (
        max(float(ev_power_kw), 0.0)
        if ev_power_kw is not None
        else None
    )
    ev_active = ev_charging is True or (
        reported_ev is not None and reported_ev > 0.1
    )
    valid_ev = not ev_active or (
        reported_ev is not None
        and not ev_power_stale
        and reported_ev > 0.0
        and reported_ev * hours <= load + 1e-6
    )
    if not valid_ev:
        # Unknown load split: never treat a possible EV load as battery-home
        # demand. The site-input cap is a diagnostic, not an EV throttling tool.
        pv_charge = min(solar, charge_budget, max(capacity - stored, 0.0) / charge_eff)
        return NoExportCheapFlow(
            grid_import_kwh=max(load, (reported_ev or 0.0) * hours),
            grid_to_ev_kwh=(reported_ev or 0.0) * hours,
            grid_to_home_kwh=load,
            grid_to_battery_input_kwh=0.0,
            solar_to_home_kwh=0.0,
            solar_to_battery_input_kwh=pv_charge,
            solar_curtailed_kwh=max(solar - pv_charge, 0.0),
            battery_to_home_kwh=0.0,
            battery_stored_kwh=min(stored + pv_charge * charge_eff, capacity),
            ev_evidence_valid=False,
        )

    ev_grid = (reported_ev or 0.0) * hours if ev_active else 0.0
    home = max(load - ev_grid, 0.0)
    solar_home = min(solar, home, inverter_budget)
    solar_surplus = max(solar - solar_home, 0.0)
    pv_charge = min(
        solar_surplus,
        charge_budget,
        max(capacity - stored, 0.0) / charge_eff,
    )
    after_pv = min(stored + pv_charge * charge_eff, capacity)

    floor = reserve if target_stored_kwh is None else min(
        max(float(target_stored_kwh), reserve), capacity
    )
    net_home = max(home - solar_home, 0.0)
    battery_home = min(
        net_home,
        discharge_budget,
        max(inverter_budget - solar_home, 0.0),
        max(after_pv - floor, 0.0) * discharge_eff,
    )
    after_home = after_pv - battery_home / discharge_eff
    house_grid = max(net_home - battery_home, 0.0)

    grid_charge = 0.0
    if target_stored_kwh is not None and after_home + 1e-9 < floor:
        import_headroom = (
            float("inf")
            if site_import_limit_kw is None
            else max(float(site_import_limit_kw) * hours - ev_grid - house_grid, 0.0)
        )
        grid_charge = min(
            max(charge_budget - pv_charge, 0.0),
            max(floor - after_home, 0.0) / charge_eff,
            import_headroom,
        )

    return NoExportCheapFlow(
        grid_import_kwh=ev_grid + house_grid + grid_charge,
        grid_to_ev_kwh=ev_grid,
        grid_to_home_kwh=house_grid,
        grid_to_battery_input_kwh=grid_charge,
        solar_to_home_kwh=solar_home,
        solar_to_battery_input_kwh=pv_charge,
        solar_curtailed_kwh=max(solar_surplus - pv_charge, 0.0),
        battery_to_home_kwh=battery_home,
        battery_stored_kwh=min(after_home + grid_charge * charge_eff, capacity),
        ev_evidence_valid=True,
    )
