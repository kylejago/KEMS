"""Conservative retirement of unused KEMS scenario *presentation* entities.

The internal scenario/forecast/ROI models and the two No-KEMS cost sensors
remain untouched. Never remove an entity from another integration or a live
custom scenario presentation whose state may still be used by the owner.
"""

from __future__ import annotations

from typing import Any

# Exact KEMS unique-ID suffixes. No prefix-matching or wildcard registry edits.
RETIRED_SCENARIO_SENSOR_KEYS = (
    "compare_solar_only_cost_today",
    "compare_solar_battery_cost_today",
    "compare_kems_no_export_cost_today",
    "compare_kems_full_cost_today",
    "compare_kems_forecast_cost_today",
    "compare_full_island_mode_today",
    "compare_full_island_load_served_today",
    "compare_full_island_eps_demand_today",
    "compare_full_island_ev_energy_shed_today",
    "compare_full_island_unserved_energy_today",
    "compare_full_island_ending_soc_today",
    "compare_full_island_prepared_status_today",
    "compare_full_island_required_starting_soc_today",
    "compare_full_island_prepared_target_soc_today",
    "compare_full_island_prepared_load_served_today",
    "compare_full_island_prepared_unserved_energy_today",
    "compare_no_system_flow_now",
    "compare_solar_only_flow_now",
    "compare_solar_battery_flow_now",
    "compare_kems_no_export_flow_now",
    "compare_kems_full_flow_now",
    "compare_kems_forecast_flow_now",
    "compare_full_island_flow_now",
)


def _is_inactive_scenario_presentation(current: Any) -> bool:
    """Only retire missing, explicitly unavailable, or all-sentinel states."""
    if current is None:
        return True
    state = str(current.state).strip()
    if state.lower() in {"unknown", "unavailable"}:
        return True
    # The obsolete flow entities report this literal no-data sentinel when
    # scenario simulation is switched off; never remove a real measured flow.
    return state == "H=-1,S=-1,GI=-1,GE=-1,SH=-1,SB=-1,SE=-1,GB=-1,BH=-1,BE=-1,SOC=-1"


def retire_inactive_scenario_sensors(
    registry: Any,
    states: Any,
    *,
    entry_id: str,
) -> tuple[str, ...]:
    """Prune only this config entry's exact KEMS-owned inactive scenario UI.

    Called *after* platform setup. Live/active legacy values are left in the
    registry for owner review rather than silently breaking an automation.
    This has no impact on the scenario engine, forecasts, dispatch or ROI.
    """
    removed: list[str] = []
    for key in RETIRED_SCENARIO_SENSOR_KEYS:
        unique_id = f"{entry_id}_{key}"
        entity_id = registry.async_get_entity_id("sensor", "kems", unique_id)
        if not entity_id:
            continue
        entity = registry.entities.get(entity_id)
        if (
            entity is None
            or entity.platform != "kems"
            or entity.config_entry_id != entry_id
            or entity.unique_id != unique_id
        ):
            continue
        if not _is_inactive_scenario_presentation(states.get(entity_id)):
            continue
        registry.async_remove(entity_id)
        removed.append(entity_id)
    return tuple(removed)
