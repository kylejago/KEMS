"""Stable Home Assistant state for the customer-facing Agile slot table."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

ENTITY_ID = "sensor.kems_agile_slots"

_PRESENTATION_ALIASES = {
    "ending_soc_percent": "flow_estimated_soc_percent",
    "grid_import_kwh": "flow_grid_import_kwh",
    "grid_export_kwh": "flow_grid_export_kwh",
    "solar_generation_kwh": "flow_solar_kwh",
    "solar_to_home_kwh": "flow_solar_to_home_kwh",
    "solar_to_battery_kwh": "flow_solar_to_battery_kwh",
    "solar_export_kwh": "flow_solar_export_kwh",
    "grid_to_battery_kwh": "flow_grid_to_battery_kwh",
    "battery_to_home_kwh": "flow_battery_to_home_kwh",
    "battery_export_kwh": "flow_battery_export_kwh",
}


def _agile_state(coordinator: Any) -> dict[str, Any]:
    """Return the retained Agile state as a normal dictionary."""
    value = getattr(coordinator, "agile_smart_export_state", None)
    return value if isinstance(value, dict) else {}


def _presentation_slot(slot: Any) -> Any:
    """Mirror canonical flow presentation fields onto legacy slot aliases.

    The Pi/Web Agile table historically consumed the settled/replay field names.
    Active and future rows now carry canonical ``flow_*`` values after rolling
    replans and SOC rebasing.  Keep both contracts coherent on this deliberately
    customer-facing compatibility entity without mutating the optimiser state.
    """
    if not isinstance(slot, dict):
        return slot

    presented = dict(slot)
    mirrored = False
    for legacy_field, canonical_field in _PRESENTATION_ALIASES.items():
        canonical_value = presented.get(canonical_field)
        if canonical_value is None:
            continue
        presented[legacy_field] = canonical_value
        mirrored = True

    if mirrored:
        presented["presentation_source"] = "canonical flow presentation"
        presented["presentation_reporting_only"] = True
        presented["presentation_hardware_writes"] = "blocked"
    return presented


def _presentation_slots(value: Any) -> list[Any]:
    """Return detached presentation rows with canonical/legacy parity."""
    if not isinstance(value, list):
        return []
    return [_presentation_slot(slot) for slot in value]


def _utc_time(value: Any) -> datetime | None:
    """Decode provider timestamps without guessing a timezone."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _finite_nonnegative(value: Any) -> float | None:
    """Keep projected presentation numbers finite and non-negative."""
    import math

    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _physical_live_slot_outlook(coordinator: Any, state: dict[str, Any]) -> dict[str, Any]:
    """Project *live physical* SOC through the already-reviewed Agile ledger.

    This is reporting-only: no changes to the digital twin, export schedule,
    command authority, reserve or FoxESS writes. Fail closed to unavailable
    rather than mixing physical SOC with simulated slot-action annotations.
    """
    plan = state.get("rolling_export_plan")
    if not isinstance(plan, dict) or plan.get("available") is not True:
        return {}
    proof = plan.get("physical_planning_evidence")
    schedule = plan.get("forecast_path_scheduler")
    if (
        not isinstance(proof, dict)
        or proof.get("available") is not True
        or plan.get("planning_soc_source") != "verified FoxESS physical lower bound"
        or not isinstance(schedule, dict)
        or schedule.get("available") is not True
        or schedule.get("active") is not True
        or schedule.get("future_solar_borrowing") is not False
    ):
        return {}
    generated = _utc_time(plan.get("generated_at"))
    now = datetime.now(UTC)
    if generated is None or not timedelta(0) <= now - generated <= timedelta(minutes=5):
        return {}
    soc = _finite_nonnegative(plan.get("planning_soc_percent"))
    if soc is None or soc > 100:
        return {}
    simulation = getattr(getattr(coordinator, "settings", None), "simulation", None)
    capacity = _finite_nonnegative(getattr(simulation, "battery_capacity_kwh", None))
    discharge_efficiency = _finite_nonnegative(
        getattr(simulation, "discharge_efficiency", None)
    )
    if (
        capacity is None
        or capacity <= 0
        or discharge_efficiency is None
        or not 0 < discharge_efficiency <= 1
    ):
        return {}
    # The scheduler's slot-energy ledger is discharged chronologically.
    # An unsupported future solar recharge cannot be projected from total
    # net energy alone, so do not publish an invented per-slot battery SOC.
    stored_solar = _finite_nonnegative(schedule.get("forecast_solar_stored_kwh"))
    if stored_solar is None or stored_solar > 0:
        return {}
    allocations = schedule.get("allocations")
    if not isinstance(allocations, list) or not allocations:
        return {}
    result: dict[str, Any] = {}
    previous_end: datetime | None = None
    for allocation in allocations:
        if not isinstance(allocation, dict):
            return {}
        start = _utc_time(allocation.get("valid_from"))
        end = _utc_time(allocation.get("valid_to"))
        discharged = _finite_nonnegative(allocation.get("planned_total_discharge_kwh"))
        exported = _finite_nonnegative(allocation.get("planned_battery_export_kwh"))
        to_house = _finite_nonnegative(allocation.get("planned_house_battery_kwh"))
        if (
            start is None
            or end is None
            or end <= start
            or (previous_end is not None and start < previous_end)
            or discharged is None
            or exported is None
            or to_house is None
        ):
            return {}
        previous_end = end
        if discharged + 0.02 < exported + to_house:
            return {}
        soc = max(0.0, soc - 100.0 * discharged / (capacity * discharge_efficiency))
        if end <= now:
            continue
        if exported > 0.01:
            action = "Planned battery export; house first"
        elif to_house > 0.01:
            action = "Battery powers home; no deliberate battery export planned"
        else:
            action = "No battery discharge scheduled"
        result[str(allocation["valid_from"])] = {
            "estimated_soc_percent": round(soc, 1),
            "action": action,
            "basis": "verified physical planning SOC + chronological live ledger",
            "reporting_only": True,
        }
    expected_end = _finite_nonnegative(schedule.get("ending_soc_percent"))
    if expected_end is None or abs(soc - expected_end) > 1.0:
        return {}
    return result


def _attributes(coordinator: Any) -> dict[str, Any]:
    """Return the slot payload used by the rebuilt dashboard and Pi/Web."""
    state = _agile_state(coordinator)
    quality = state.get("price_quality")
    if not isinstance(quality, dict):
        quality = {}

    today_slots = _presentation_slots(state.get("today_slots"))
    tomorrow_slots = _presentation_slots(state.get("tomorrow_slots"))
    live_outlook = _physical_live_slot_outlook(coordinator, state)

    periods = state.get("periods")
    periods = periods if isinstance(periods, dict) else {}
    today = periods.get("today")
    today = today if isinstance(today, dict) else {}
    today_agile = today.get("agile_smart_export")
    today_agile = today_agile if isinstance(today_agile, dict) else {}

    today_expected = int(quality.get("today_expected") or 48)
    tomorrow_expected = int(quality.get("tomorrow_expected") or 48)
    today_count = int(quality.get("today_count") or len(today_slots))
    tomorrow_count = int(quality.get("tomorrow_count") or len(tomorrow_slots))

    return {
        "friendly_name": "KEMS Agile slots",
        "region": state.get("region"),
        "product_code": state.get("product_code"),
        "tariff_code": state.get("tariff_code"),
        "current_rate_pence": state.get("current_rate_pence"),
        "current_action": state.get("current_action"),
        "today_count": today_count,
        "today_expected": today_expected,
        "today_complete": bool(quality.get("today_complete")),
        "tomorrow_count": tomorrow_count,
        "tomorrow_expected": tomorrow_expected,
        "tomorrow_complete": bool(quality.get("tomorrow_complete")),
        "tomorrow_status": quality.get("tomorrow_status")
        or "awaiting Octopus publication",
        "today_missing_slots": quality.get("today_missing_slots") or [],
        "tomorrow_missing_labels": quality.get("tomorrow_missing_labels") or [],
        "today_slots": today_slots,
        "physical_live_slot_outlook": live_outlook,
        "physical_live_slot_outlook_available": bool(live_outlook),
        "physical_live_slot_outlook_basis": (
            "verified FoxESS physical lower bound + live chronological Agile allocation"
            if live_outlook
            else "unavailable: do not substitute simulated SOC for physical SOC"
        ),
        "tomorrow_slots": tomorrow_slots,
        "today_agile": today_agile,
        "current_day_settlement_reconciliation": state.get(
            "current_day_settlement_reconciliation"
        ),
        "presentation_contract": (
            "canonical flow fields mirrored onto legacy aliases for Pi/Web parity"
        ),
        "reporting_only": True,
        "hardware_writes": "blocked",
    }


def async_setup_agile_slots_state(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: Any,
) -> None:
    """Publish a stable slot entity and refresh it with the coordinator."""

    def publish() -> None:
        attributes = _attributes(coordinator)
        hass.states.async_set(
            ENTITY_ID,
            f"{attributes['today_count']}/{attributes['today_expected']} today",
            attributes,
        )

    publish()
    entry.async_on_unload(coordinator.async_add_listener(publish))
