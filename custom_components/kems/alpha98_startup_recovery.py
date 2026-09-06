"""Alpha9.8 bounded startup recovery for late Home Assistant source states.

A Home Assistant restart can initialise KEMS before non-FoxESS integrations have
published their first usable states.  The first KEMS analysis can then complete
with an intentionally unavailable live snapshot even though those source entities
became usable while that relatively expensive first analysis was running.

This helper detects only that narrow transition and allows one additional KEMS
coordinator refresh during setup.  Physical FoxESS battery/solar/grid-export
telemetry is deliberately excluded: commissioning availability and every hardware
write boundary remain unchanged.
"""

from __future__ import annotations

from typing import Any

_INVALID_STATES = {"unknown", "unavailable", "none", ""}
_FOXESS_SOURCE_MARKERS = ("foxess", ".kh7_", "_kh7")

# Snapshot fields that are useful immediately at startup and are allowed to
# recover from normal Home Assistant integrations.  Physical battery, PV and
# grid-export fields are intentionally absent from this table.
_RECOVERABLE_FIELDS = (
    ("current_import_rate", "current_import_rate"),
    ("next_import_rate", "next_import_rate"),
    ("electricity_standing_charge", "electricity_standing_charge"),
    ("off_peak", "off_peak"),
    ("intelligent_slot", "intelligent_slot"),
    ("gas_current_rate", "gas_current_rate"),
    ("gas_standing_charge", "gas_standing_charge"),
    ("gas_meter_total_kwh", "gas_meter_total"),
    ("gas_usage_today_kwh", "gas_usage_today"),
    ("gas_cost_today_pence", "gas_cost_today"),
    ("ev_connected", "ev_status"),
    ("ev_charging", "ev_status"),
    ("ev_power_kw", "ev_power_kw"),
    ("ev_soc", "ev_soc"),
    ("house_load_kw", "house_load_kw"),
    ("grid_import_kw", "grid_import_kw"),
)


def _source_state_usable(hass: Any, entity_id: str | None) -> bool:
    """Return whether one mapped source currently has a usable HA state."""
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    if state is None:
        return False
    return str(state.state).strip().casefold() not in _INVALID_STATES


def _is_physical_foxess_source(entity_id: str | None) -> bool:
    """Keep pre-commissioning FoxESS telemetry out of startup recovery."""
    if not entity_id:
        return False
    normalised = entity_id.casefold()
    return any(marker in normalised for marker in _FOXESS_SOURCE_MARKERS)


def startup_source_recovery_fields(
    hass: Any,
    entities: Any,
    snapshot: Any,
) -> tuple[str, ...]:
    """Return missing snapshot fields whose mapped non-FoxESS source is now usable."""
    recovered: list[str] = []
    seen_entities: set[str] = set()
    for snapshot_field, entity_field in _RECOVERABLE_FIELDS:
        if getattr(snapshot, snapshot_field, None) is not None:
            continue
        entity_id = getattr(entities, entity_field, None)
        if not entity_id or entity_id in seen_entities:
            continue
        seen_entities.add(entity_id)
        if _is_physical_foxess_source(entity_id):
            continue
        if _source_state_usable(hass, entity_id):
            recovered.append(snapshot_field)
    return tuple(recovered)


async def async_recover_alpha98_startup_sources(
    hass: Any, coordinator: Any
) -> tuple[str, ...]:
    """Run at most one extra coordinator refresh for sources that arrived mid-setup."""
    data = getattr(coordinator, "data", None)
    snapshot = getattr(data, "snapshot", None)
    entities = getattr(coordinator, "entities", None)
    if snapshot is None or entities is None:
        return ()

    fields = startup_source_recovery_fields(hass, entities, snapshot)
    if not fields:
        return ()

    # This function is called once from async_setup_entry after the successful
    # first refresh.  There is deliberately no retry loop or timer here.
    await coordinator.async_refresh()
    return fields
