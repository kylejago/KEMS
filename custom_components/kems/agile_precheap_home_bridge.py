"""Final pre-cheap home-load protection for Agile replay and routing truth.

The Agile deadline targets the battery reserve at the configured cheap-window
start, not before it.  A partially published Tomorrow horizon must therefore keep
enough stored energy above that reserve to serve forecast net house demand until
the cheap boundary, even when the remaining export prices have not published.

This canonical layer runs last in the Alpha7 compatibility boundary.  It only
raises an inherited replay floor when a real cheap boundary is present in the
replay records; it never lowers an existing forecast/safety floor.  The same
layer also prevents display enrichment from classifying non-cheap protected
house import as grid-to-battery charging.  Real hardware writes remain blocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime_base
from .kems_core import SimulationConfig, Snapshot

_EPSILON = 1e-9


def _future_net_house_ac_kwh(
    self,
    records: list[Snapshot],
    index: int,
    config: SimulationConfig,
) -> tuple[float, bool]:
    """Return forecast net house AC energy after this slot until cheap power."""
    needed_ac = 0.0
    reached_cheap = False
    for future, following in zip(
        records[index + 1 :],
        records[index + 2 :],
        strict=False,
    ):
        if future.cheap_period_confirmed:
            reached_cheap = True
            break
        hours = min(
            max(
                (following.timestamp - future.timestamp).total_seconds(),
                0.0,
            )
            / 3600.0,
            0.5,
        )
        if hours <= 0.0:
            continue
        load_kw = agile._load(future)
        if load_kw is None:
            continue
        load_kw = max(float(load_kw), 0.0)
        solar_kw = max(
            float(self._simulation._simulated_solar_power(future, config)),
            0.0,
        )
        solar_to_home_kw = min(
            solar_kw,
            load_kw,
            max(float(config.inverter_limit_kw), 0.0),
        )
        needed_ac += max(load_kw - solar_to_home_kw, 0.0) * hours
    return needed_ac, reached_cheap


def _floor_with_precheap_home_bridge(
    self,
    records: list[Snapshot],
    index: int,
    current: Snapshot,
    config: SimulationConfig,
    reserve: float,
    capacity: float,
) -> float:
    """Never reach the reserve before the remaining home-load bridge is served."""
    inherited = float(
        _original_floor(
            self,
            records,
            index,
            current,
            config,
            reserve,
            capacity,
        )
    )
    needed_ac, reached_cheap = _future_net_house_ac_kwh(
        self,
        records,
        index,
        config,
    )
    if not reached_cheap:
        return inherited

    bridge_floor = reserve + needed_ac / max(
        float(config.discharge_efficiency),
        0.01,
    )
    return min(
        max(inherited, reserve, bridge_floor),
        capacity,
    )


def _slot_has_confirmed_cheap_record(
    slot: dict[str, Any],
    records: list[Snapshot],
) -> bool:
    """Return whether any replay record inside the slot is a confirmed cheap period."""
    try:
        start = datetime.fromisoformat(str(slot["valid_from"])).astimezone(UTC)
        end = datetime.fromisoformat(str(slot["valid_to"])).astimezone(UTC)
    except (KeyError, TypeError, ValueError):
        return False
    for record in records:
        timestamp = record.timestamp.astimezone(UTC)
        if start <= timestamp < end and record.cheap_period_confirmed:
            return True
    return False


def _enrich_slot_routing_with_import_truth(
    slots_value: Any,
    records: list[Snapshot],
    config: SimulationConfig,
    simulation: Any,
) -> None:
    """Keep non-cheap grid import classified as house import, never battery charge."""
    _original_enrich_slot_routing(slots_value, records, config, simulation)
    if not isinstance(slots_value, list):
        return
    for slot in slots_value:
        if not isinstance(slot, dict) or slot.get("grid_import_kwh") is None:
            continue
        try:
            grid_import = max(float(slot.get("grid_import_kwh") or 0.0), 0.0)
        except (TypeError, ValueError):
            continue
        if grid_import <= _EPSILON:
            slot["grid_to_battery_kwh"] = 0.0
            continue
        if not _slot_has_confirmed_cheap_record(slot, records):
            slot["grid_to_battery_kwh"] = 0.0


def install_precheap_home_bridge() -> None:
    """Install final replay floor and routing-truth reconciliation exactly once."""
    global _original_enrich_slot_routing
    global _original_floor

    floor = agile.AgileSmartExportManager._floor
    if not getattr(floor, "_kems_precheap_home_bridge", False):
        _original_floor = floor
        _floor_with_precheap_home_bridge._kems_precheap_home_bridge = True
        agile.AgileSmartExportManager._floor = _floor_with_precheap_home_bridge

    enrich = runtime_base._enrich_slot_routing
    if getattr(enrich, "_kems_precheap_import_truth", False):
        return
    _original_enrich_slot_routing = enrich
    _enrich_slot_routing_with_import_truth._kems_precheap_import_truth = True
    runtime_base._enrich_slot_routing = _enrich_slot_routing_with_import_truth
