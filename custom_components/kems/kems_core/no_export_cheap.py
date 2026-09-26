"""Evidence-aware cheap routing for the No paid export proposal.

A confirmed cheap tariff is necessary but not sufficient evidence for separating
EV and household power. The FoxESS Load Power mapping alone does not prove
whether a separately metered Ohme charger is included in that reading.
This module is pure: it never authorises or writes inverter commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from math import isfinite
from zoneinfo import ZoneInfo

from .models import SimulationConfig, Snapshot

_UK = ZoneInfo("Europe/London")
_OVERNIGHT_START = time(23, 30)
_OVERNIGHT_END = time(5, 30)


def no_export_cheap_period_kind(snapshot: Snapshot) -> str | None:
    """Distinguish scheduled overnight cheap power from confirmed extra slots."""
    if not snapshot.cheap_period_confirmed:
        return None
    clock = snapshot.timestamp.astimezone(_UK).time().replace(tzinfo=None)
    if clock >= _OVERNIGHT_START or clock < _OVERNIGHT_END:
        return "overnight"
    return "extra_intelligent"


@dataclass(frozen=True, slots=True)
class DemandSplit:
    """One site-load accounting boundary, with no inferred EV attribution."""

    site_kw: float
    house_kw: float
    ev_grid_kw: float
    ev_separation_proven: bool
    reason: str


def split_no_export_demand(snapshot: Snapshot, load_kw: float) -> DemandSplit:
    """Split a proven measurement once; never silently subtract/double-count EV.

    ev_load_in_house_load is a measured, explicitly recorded provenance flag.
    When unknown, the entire recorded load is kept as one opaque site demand:
    no EV-only grid attribution is claimed and cheap battery discharge must be
    held conservatively while EV charging is observed.
    """
    load = max(float(load_kw), 0.0)
    active = snapshot.ev_charging is True or (
        snapshot.ev_power_kw is not None and snapshot.ev_power_kw > 0.1
    )
    if not active:
        return DemandSplit(load, load, 0.0, True, "EV not charging")
    power = snapshot.ev_power_kw
    if (
        power is None
        or "ev_power_kw" in snapshot.stale_fields
        or not isfinite(float(power))
        or power <= 0.0
    ):
        return DemandSplit(load, load, 0.0, False, "Ohme power unavailable")
    ev = float(power)
    if snapshot.ev_load_in_house_load is True and ev <= load + 0.05:
        return DemandSplit(load, max(load - ev, 0.0), ev, True, "EV included in load")
    if snapshot.ev_load_in_house_load is False:
        return DemandSplit(load + ev, load, ev, True, "EV outside load")
    return DemandSplit(load, load, 0.0, False, "EV/load measurement scope unproven")


def infer_ev_load_in_house_load(
    *,
    house_kw: float | None,
    ev_kw: float | None,
    solar_kw: float | None,
    battery_kw: float | None,
    grid_import_kw: float | None,
    grid_export_kw: float | None,
    battery_positive_is_discharge: bool,
) -> bool | None:
    """Return a candidate only when the independent site balance distinguishes it.

    This is one candidate observation, not physical isolation or live write
    authority. The collector must see repeated consistent candidates; an
    ambiguous, missing or conflicting reading must clear the evidence.
    """
    readings = (house_kw, ev_kw, solar_kw, battery_kw, grid_import_kw, grid_export_kw)
    if any(value is None or not isfinite(float(value)) for value in readings):
        return None
    house = max(float(house_kw), 0.0)
    ev = max(float(ev_kw), 0.0)
    if ev < 1.0:
        return None
    battery = float(battery_kw) * (1 if battery_positive_is_discharge else -1)
    site = max(
        float(solar_kw) + battery + float(grid_import_kw) - float(grid_export_kw),
        0.0,
    )
    tolerance = max(0.40, 0.06 * max(site, house + ev))
    included = abs(site - house) <= tolerance
    excluded = abs(site - (house + ev)) <= tolerance
    if included == excluded:
        return None
    return included


@dataclass(frozen=True, slots=True)
class CheapRoute:
    """Energy quantities for one verified cheap interval, in kWh."""

    kind: str
    site_load_kwh: float
    ev_grid_kwh: float
    house_grid_kwh: float
    solar_to_home_kwh: float
    solar_to_battery_input_kwh: float
    grid_to_battery_input_kwh: float
    battery_to_home_kwh: float
    battery_stored_kwh: float
    solar_curtailed_kwh: float
    grid_import_kwh: float
    ev_separation_proven: bool
    evidence_reason: str


def route_no_export_cheap(
    snapshot: Snapshot,
    *,
    load_kw: float,
    solar_kw: float,
    battery_kwh: float,
    target_stored_kwh: float,
    config: SimulationConfig,
    hours: float,
    allow_grid_charge: bool = True,
) -> CheapRoute:
    """Preserve target as a FLOOR; use above-floor energy only for house load.

    The EV is always a grid allocation in the proposed twin *when measured EV
    membership is proven*. Without that evidence, hold battery discharge and
    retain raw site load, rather than fabricate an EV/house split.
    """
    kind = no_export_cheap_period_kind(snapshot)
    if kind is None:
        raise ValueError("No-export cheap routing requires confirmed cheap time")
    split = split_no_export_demand(snapshot, load_kw)
    duration = max(float(hours), 0.0)
    capacity = max(config.battery_capacity_kwh, 0.1)
    reserve = capacity * config.battery_reserve_percent / 100
    stored = min(max(float(battery_kwh), reserve), capacity)
    floor = min(max(float(target_stored_kwh), reserve), capacity)
    solar = max(float(solar_kw), 0.0) * duration
    inverter = max(config.inverter_limit_kw, 0.0) * duration
    house = split.house_kw * duration
    ev_grid = split.ev_grid_kw * duration

    solar_home = min(solar, house, inverter)
    net_house = max(house - solar_home, 0.0)
    battery_home = (
        min(
            net_house,
            max(config.max_discharge_kw, 0.0) * duration,
            max(inverter - solar_home, 0.0),
            max(stored - floor, 0.0) * config.discharge_efficiency,
        )
        if split.ev_separation_proven
        else 0.0
    )
    stored -= battery_home / max(config.discharge_efficiency, 0.01)
    house_grid = max(net_house - battery_home, 0.0)

    solar_left = max(solar - solar_home, 0.0)
    solar_charge_input = min(
        solar_left,
        max(config.max_charge_kw, 0.0) * duration,
        max(capacity - stored, 0.0) / max(config.charge_efficiency, 0.01),
    )
    stored += solar_charge_input * config.charge_efficiency
    charge_headroom = max(
        max(config.max_charge_kw, 0.0) * duration - solar_charge_input, 0.0
    )
    site_headroom = (
        float("inf")
        if config.site_import_limit_kw is None
        else max(config.site_import_limit_kw * duration - ev_grid - house_grid, 0.0)
    )
    grid_charge_input = (
        min(
            charge_headroom,
            max(floor - stored, 0.0) / max(config.charge_efficiency, 0.01),
            site_headroom,
        )
        if allow_grid_charge
        else 0.0
    )
    stored += grid_charge_input * config.charge_efficiency
    return CheapRoute(
        kind=kind,
        site_load_kwh=split.site_kw * duration,
        ev_grid_kwh=ev_grid,
        house_grid_kwh=house_grid,
        solar_to_home_kwh=solar_home,
        solar_to_battery_input_kwh=solar_charge_input,
        grid_to_battery_input_kwh=grid_charge_input,
        battery_to_home_kwh=battery_home,
        battery_stored_kwh=min(max(stored, reserve), capacity),
        solar_curtailed_kwh=max(solar_left - solar_charge_input, 0.0),
        grid_import_kwh=ev_grid + house_grid + grid_charge_input,
        ev_separation_proven=split.ev_separation_proven,
        evidence_reason=split.reason,
    )
