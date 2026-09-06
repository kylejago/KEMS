"""Simulation-only demand fallback that cannot authorise physical control.

FoxESS source authority is intentionally retained for commissioning, shadow and
future control.  Before that telemetry is usable, however, KEMS may still have a
fresh Octopus current-demand observation that historically powered the virtual
simulation.  This module keeps those two evidence domains separate.

A fallback value is copied into the normal Snapshot demand field but the physical
field remains explicitly stale.  A provenance marker in ``source_age_seconds``
allows only the simulation replay to consume that value.  Control and
commissioning continue to see the stale physical field and therefore fail closed.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

SIMULATION_DEMAND_FIELDS = frozenset({"house_load_kw", "grid_import_kw"})
_FALLBACK_AGE_PREFIX = "simulation_fallback_"
_OCTOPUS_ELECTRICITY_PREFIX = "sensor.octopus_energy_electricity_"
_CURRENT_RATE_SUFFIX = "_current_rate"
_CURRENT_DEMAND_SUFFIX = "_current_demand"


def simulation_fallback_age_key(field: str) -> str:
    """Return the retained provenance key for one simulation-only fallback."""
    return f"{_FALLBACK_AGE_PREFIX}{field}"


def resolve_octopus_current_demand_entity(
    *,
    house_load_entity: str | None,
    grid_import_entity: str | None,
    current_import_rate_entity: str | None,
    state_exists: Callable[[str], bool],
) -> str | None:
    """Recover the Octopus current-demand source after FoxESS promotion.

    Existing Octopus house/grid mappings remain the first choice.  If source
    authority has already promoted both shared roles to FoxESS Modbus, derive the
    sibling current-demand entity from the still-authoritative Octopus current-rate
    entity.  The derived entity must actually exist in Home Assistant; no guessed
    source is returned.
    """
    candidates: list[str] = []
    for entity_id in (grid_import_entity, house_load_entity):
        if (
            entity_id
            and entity_id.startswith(_OCTOPUS_ELECTRICITY_PREFIX)
            and entity_id not in candidates
        ):
            candidates.append(entity_id)

    rate_entity = current_import_rate_entity or ""
    if rate_entity.startswith(_OCTOPUS_ELECTRICITY_PREFIX) and rate_entity.endswith(
        _CURRENT_RATE_SUFFIX
    ):
        derived = rate_entity[: -len(_CURRENT_RATE_SUFFIX)] + _CURRENT_DEMAND_SUFFIX
        if derived not in candidates:
            candidates.append(derived)

    return next(
        (entity_id for entity_id in candidates if state_exists(entity_id)), None
    )


@dataclass(frozen=True, slots=True)
class SimulationDemandEvidence:
    """Demand values plus physical freshness and simulation provenance."""

    house_load_kw: float | None
    grid_import_kw: float | None
    source_age_seconds: dict[str, float]
    stale_fields: tuple[str, ...]
    fallback_fields: tuple[str, ...]


def apply_simulation_demand_fallback(
    *,
    physical_house_load_kw: float | None,
    physical_grid_import_kw: float | None,
    physical_source_age_seconds: Mapping[str, float],
    physical_stale_fields: tuple[str, ...],
    fallback_demand_kw: float | None,
    fallback_age_seconds: float | None,
) -> SimulationDemandEvidence:
    """Use fresh Octopus demand only where physical demand is unavailable.

    The original physical stale flags are retained.  If FoxESS returned ``None``
    without marking a just-published ``unavailable`` state stale, this helper adds
    the corresponding physical stale flag before exposing the fallback.  Hardware
    safety therefore never treats Octopus demand as commissioned FoxESS evidence.
    """
    house = physical_house_load_kw
    grid_import = physical_grid_import_kw
    ages = dict(physical_source_age_seconds)
    stale = set(physical_stale_fields)
    fallback_fields: list[str] = []

    try:
        demand = float(fallback_demand_kw) if fallback_demand_kw is not None else None
    except (TypeError, ValueError):
        demand = None
    if demand is not None and not math.isfinite(demand):
        demand = None

    try:
        fallback_age = (
            max(float(fallback_age_seconds), 0.0)
            if fallback_age_seconds is not None
            else 0.0
        )
    except (TypeError, ValueError):
        fallback_age = 0.0
    if not math.isfinite(fallback_age):
        fallback_age = 0.0

    if demand is not None:
        demand = max(demand, 0.0)
        for field in ("house_load_kw", "grid_import_kw"):
            current = house if field == "house_load_kw" else grid_import
            if current is not None:
                continue
            if field == "house_load_kw":
                house = demand
            else:
                grid_import = demand
            # Keep physical safety fail-closed while authorising only simulation.
            stale.add(field)
            ages[simulation_fallback_age_key(field)] = round(fallback_age, 1)
            fallback_fields.append(field)

    return SimulationDemandEvidence(
        house_load_kw=house,
        grid_import_kw=grid_import,
        source_age_seconds=ages,
        stale_fields=tuple(sorted(stale)),
        fallback_fields=tuple(fallback_fields),
    )


def install_simulation_demand_fallback_policy() -> None:
    """Teach simulation replay to recognise explicit demand-fallback provenance."""
    from . import simulation as simulation_module

    if getattr(simulation_module, "_kems_alpha99_simulation_demand_fallback", False):
        return

    original = simulation_module._fresh_snapshot_value

    def fallback_aware_snapshot_value(snapshot: Any, field: str) -> float | None:
        value = original(snapshot, field)
        if value is not None:
            return value
        if field not in SIMULATION_DEMAND_FIELDS:
            return None
        if field not in getattr(snapshot, "stale_fields", ()):
            return None
        ages = getattr(snapshot, "source_age_seconds", {})
        if not isinstance(ages, dict) or simulation_fallback_age_key(field) not in ages:
            return None
        raw = getattr(snapshot, field, None)
        if raw is None:
            return None
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    simulation_module._fresh_snapshot_value = fallback_aware_snapshot_value
    simulation_module._kems_alpha99_simulation_demand_fallback = True
