"""Simulation-only evidence adapter for customer-facing Agile replay.

Physical FoxESS freshness remains authoritative for commissioning, shadow and
future control. The Agile digital twin must instead consume the same authorised
Octopus-demand and proposal-solar evidence as the core SimulationEngine.

Alpha9.11 repaired only ``_observed_slot_details``. Live proof showed that was too
late: the underlying Agile-day optimiser had already rejected each interval on its
legacy blanket ``Snapshot.stale_fields`` gate, leaving the canonical slot fields
and simulated SOC null. Alpha9.12 adapts a detached copy of each Snapshot before
that optimiser runs. The physical Snapshot is never mutated and no hardware-write
permission can be changed here.
"""

from __future__ import annotations

from typing import Any

from . import agile_flow_presentation as flow
from . import agile_smart_export as agile
from .kems_core import SimulationConfig, Snapshot
from .kems_core import simulation as simulation_module

_PHYSICAL_ONLY_FIELDS = (
    "battery_power_kw",
    "battery_soc",
    "grid_export_kw",
)


def _simulation_load(snapshot: Snapshot) -> float | None:
    """Return demand accepted by the canonical simulation freshness policy."""
    value = simulation_module._fresh_snapshot_value(snapshot, "house_load_kw")
    if value is None:
        value = simulation_module._fresh_snapshot_value(snapshot, "grid_import_kw")
    return max(float(value), 0.0) if value is not None else None


def _simulation_snapshot_view(snapshot: Snapshot) -> Snapshot:
    """Return a detached Agile-replay view without weakening physical freshness.

    The legacy Agile optimiser rejects a whole interval whenever *any* dynamic
    source is stale. That is no longer the correct simulation contract once
    FoxESS commissioning and digital-twin evidence are separated.

    Demand is cleared from the stale set only when the canonical SimulationEngine
    freshness policy accepts it. Stale physical PV is nulled so the existing
    proposal-solar policy, rather than stale inverter telemetry, owns simulation.
    Battery and grid-export telemetry are physical-only inputs to commissioning;
    the Agile optimiser models its own virtual battery/export state, so stale
    values are nulled and removed only from this detached simulation view.

    Unknown stale fields are retained, preserving fail-closed behaviour for any
    evidence domain not explicitly covered by this contract.
    """
    data = snapshot.to_dict()
    stale = set(snapshot.stale_fields)

    house = simulation_module._fresh_snapshot_value(snapshot, "house_load_kw")
    grid = simulation_module._fresh_snapshot_value(snapshot, "grid_import_kw")
    if house is None:
        house = grid
    if grid is None:
        grid = house

    if house is not None:
        data["house_load_kw"] = max(float(house), 0.0)
        stale.discard("house_load_kw")
    if grid is not None:
        data["grid_import_kw"] = max(float(grid), 0.0)
        stale.discard("grid_import_kw")

    if "solar_power_kw" in stale:
        data["solar_power_kw"] = None
        stale.discard("solar_power_kw")

    for field in _PHYSICAL_ONLY_FIELDS:
        if field in stale:
            data[field] = None
            stale.discard(field)

    data["stale_fields"] = sorted(stale)
    return Snapshot.from_dict(data)


def _simulation_records(records: list[Snapshot]) -> list[Snapshot]:
    """Build the read-only evidence view consumed by Agile strategy replay."""
    return [_simulation_snapshot_view(item) for item in records]


def _fallback_aware_observed_slot_details(
    self: Any,
    records: list[Snapshot],
    rates: list[agile.AgileRate],
    config: SimulationConfig,
) -> dict[str, dict[str, float]]:
    """Reconstruct source fields from the already-adapted simulation evidence."""
    output: dict[str, dict[str, float]] = {}
    for current, following in zip(records, records[1:], strict=False):
        hours = min(
            max((following.timestamp - current.timestamp).total_seconds(), 0.0)
            / 3600.0,
            0.5,
        )
        if hours <= 0.0:
            continue

        rate = agile._rate_at(rates, current.timestamp)
        load = _simulation_load(current)
        following_load = _simulation_load(following)
        if (
            current.stale_fields
            or following.stale_fields
            or rate is None
            or load is None
            or following_load is None
            or current.current_import_rate is None
        ):
            continue

        key = rate.valid_from.isoformat()
        detail = output.setdefault(
            key,
            {
                "solar_generation_kwh": 0.0,
                "solar_to_home_kwh": 0.0,
                "house_load_kwh": 0.0,
            },
        )
        solar = self._simulation._simulated_solar_power(current, config) * hours
        load_kwh = max(load, 0.0) * hours
        inverter = max(config.inverter_limit_kw, 0.0) * hours
        solar_home = (
            0.0
            if current.cheap_period_confirmed
            else min(max(solar, 0.0), load_kwh, inverter)
        )
        detail["solar_generation_kwh"] += max(solar, 0.0)
        detail["solar_to_home_kwh"] += solar_home
        detail["house_load_kwh"] += load_kwh
    return output


def install_agile_slot_simulation_fallback() -> None:
    """Install the simulation-view repair exactly once on the real replay owner."""
    if getattr(flow, "_kems_alpha912_agile_replay_authority", False):
        return

    original_agile_day = flow.FlowPresentationAgileSmartExportManager._agile_day

    def agile_day_with_simulation_view(
        self: Any,
        records: list[Snapshot],
        rates: list[agile.AgileRate],
        config: SimulationConfig,
        tariff: Any,
        initial_soc: float,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return original_agile_day(
            self,
            _simulation_records(records),
            rates,
            config,
            tariff,
            initial_soc,
        )

    flow._observed_slot_details = _fallback_aware_observed_slot_details
    flow.FlowPresentationAgileSmartExportManager._agile_day = (
        agile_day_with_simulation_view
    )
    flow._kems_alpha912_agile_replay_authority = True
