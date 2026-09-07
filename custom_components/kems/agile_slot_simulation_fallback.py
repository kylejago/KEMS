"""Simulation-only demand fallback for customer-facing Agile slot replay.

Physical FoxESS freshness remains authoritative for commissioning, shadow and
future control.  The Agile slot presentation, however, must consume the same
explicitly authorised simulation-only Octopus demand fallback as the core replay.
This module changes reporting only and cannot authorise hardware writes.
"""

from __future__ import annotations

from typing import Any

from . import agile_flow_presentation as flow
from . import agile_smart_export as agile
from .kems_core import SimulationConfig, Snapshot
from .kems_core import simulation as simulation_module


def _simulation_load(snapshot: Snapshot) -> float | None:
    """Return only demand accepted by the canonical simulation freshness policy."""
    value = simulation_module._fresh_snapshot_value(snapshot, "house_load_kw")
    if value is None:
        value = simulation_module._fresh_snapshot_value(snapshot, "grid_import_kw")
    return max(float(value), 0.0) if value is not None else None


def _fallback_aware_observed_slot_details(
    self: Any,
    records: list[Snapshot],
    rates: list[agile.AgileRate],
    config: SimulationConfig,
) -> dict[str, dict[str, float]]:
    """Reconstruct slot details from the same evidence accepted by simulation.

    Do not reject an interval merely because unrelated physical FoxESS fields are
    stale.  Demand remains fail-closed unless ``_fresh_snapshot_value`` accepts it,
    which includes Alpha9.9's explicit simulation-fallback provenance.  Simulated
    solar continues through the already-authoritative SimulationEngine policy.
    """
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
            rate is None
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
    """Install the reporting repair exactly once."""
    if getattr(flow, "_kems_alpha911_slot_simulation_fallback", False):
        return
    flow._observed_slot_details = _fallback_aware_observed_slot_details
    flow._kems_alpha911_slot_simulation_fallback = True
