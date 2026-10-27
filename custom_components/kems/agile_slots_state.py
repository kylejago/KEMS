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


def _physical_live_slot_outlook(
    coordinator: Any, state: dict[str, Any]
) -> dict[str, Any]:
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
    ):
        return {}

    # An inactive high-confidence solar scheduler must not hide a *different*
    # verified physical discharge-only path. The ledger already schedules
    # home/battery energy without borrowing speculative future solar. Never
    # import the digital-twin SOC or its solar recharge into the live card.
    forecast_chronological = bool(
        isinstance(schedule, dict)
        and schedule.get("available") is True
        and schedule.get("active") is True
    )
    if forecast_chronological:
        if schedule.get("future_solar_borrowing") is not False:
            return {}
        basis = "verified physical SOC + forecast scheduler chronological replay"
    else:
        if isinstance(schedule, dict) and schedule.get("active") is True:
            return {}  # An active but invalid solar schedule is not fallback.
        ledger = plan.get("total_discharge_ledger")
        if not (
            plan.get("total_discharge_ledger_active") is True
            and isinstance(ledger, dict)
            and isinstance(ledger.get("allocations"), list)
            and ledger["allocations"]
        ):
            return {}
        unallocated = _finite_nonnegative(ledger.get("unallocated_total_discharge_kwh"))
        required = _finite_nonnegative(ledger.get("required_total_discharge_kwh"))
        allocated = _finite_nonnegative(ledger.get("allocated_total_discharge_kwh"))
        target_soc = _finite_nonnegative(
            plan.get("effective_precheap_target_soc_percent")
        )
        if (
            unallocated is None
            or unallocated > 0.05
            or required is None
            or allocated is None
            or abs(allocated - required) > 0.05
            or target_soc is None
            or target_soc > 100.0
        ):
            return {}
        schedule = {
            "allocations": ledger["allocations"],
            "forecast_solar_stored_kwh": 0.0,
            "ending_soc_percent": target_soc,
        }
        basis = (
            "verified physical SOC + chronological total-discharge ledger; "
            "no speculative solar charging credited"
        )
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
    # Prefer the scheduler's chronological SOC (including solar). Older
    # discharge-only allocations remain safely projectable from physical SOC.
    # Never interpolate aggregate solar into slots without replay evidence.
    stored_solar = _finite_nonnegative(schedule.get("forecast_solar_stored_kwh"))
    if stored_solar is None:
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
        slot_soc = _finite_nonnegative(allocation.get("ending_soc_percent"))
        if (
            start is None
            or end is None
            or end <= start
            or (previous_end is not None and start < previous_end)
            or discharged is None
            or exported is None
            or to_house is None
            or (slot_soc is not None and slot_soc > 100.0)
        ):
            return {}
        previous_end = end
        if discharged + 0.02 < exported + to_house:
            return {}
        if slot_soc is None:
            if stored_solar > 0.0:
                return {}
            soc = max(0.0, soc - 100.0 * discharged / (capacity * discharge_efficiency))
        else:
            soc = slot_soc
        if end <= now:
            continue
        if exported > 0.01:
            action = "Planned battery export; house first"
        elif to_house > 0.01:
            action = "Battery powers home; no deliberate battery export planned"
        else:
            action = "Solar recharge / hold; no battery discharge scheduled"
        result[str(allocation["valid_from"])] = {
            "estimated_soc_percent": round(soc, 1),
            "action": action,
            "basis": basis,
            "reporting_only": True,
        }
    expected_end = _finite_nonnegative(schedule.get("ending_soc_percent"))
    if expected_end is None or abs(soc - expected_end) > 1.0:
        return {}
    return result


def _advisory_live_slot_outlook(state: dict[str, Any]) -> dict[str, Any]:
    """Show the published economic plan when physical SOC replay is unavailable.

    Power Down intentionally suspends physical *Agile optimisation* proof. That
    must never erase the operator-facing planned actions. This fallback has no
    estimated SOC, never authorises export, and does not feed the optimizer,
    physical reserve guard or inverter control.
    """
    plan = state.get("rolling_export_plan")
    if not isinstance(plan, dict) or plan.get("available") is not True:
        return {}
    generated = _utc_time(plan.get("generated_at"))
    now = datetime.now(UTC)
    if generated is None or not timedelta(0) <= now - generated <= timedelta(minutes=5):
        return {}
    selected = plan.get("selected_slots")
    if not isinstance(selected, list):
        return {}
    allocations: dict[str, dict[str, Any]] = {}
    for slot in selected:
        if not isinstance(slot, dict):
            return {}
        start = _utc_time(slot.get("valid_from"))
        end = _utc_time(slot.get("valid_to"))
        exported = _finite_nonnegative(slot.get("planned_battery_export_kwh"))
        house = _finite_nonnegative(slot.get("planned_battery_to_home_kwh"))
        if (
            start is None
            or end is None
            or end <= start
            or exported is None
            or house is None
        ):
            return {}
        allocations[start.isoformat()] = slot

    priority = state.get("power_down_priority")
    priority = priority if isinstance(priority, dict) else {}
    pd_start = _utc_time(priority.get("start"))
    pd_end = _utc_time(priority.get("end"))
    pd_joined = priority.get("joined") is True
    today = state.get("today_slots")
    if not isinstance(today, list):
        return {}
    result: dict[str, Any] = {}
    for slot in today:
        if not isinstance(slot, dict):
            continue
        start = _utc_time(slot.get("valid_from"))
        end = _utc_time(slot.get("valid_to"))
        if start is None or end is None or end <= now:
            continue
        selected_slot = allocations.get(start.isoformat())
        if (
            pd_joined
            and pd_start is not None
            and pd_end is not None
            and start < pd_end
            and end > pd_start
        ):
            action = "Power Down priority — safe export"
        elif selected_slot and selected_slot["planned_battery_export_kwh"] > 0.01:
            action = "Agile battery export planned"
        elif selected_slot and selected_slot["planned_battery_to_home_kwh"] > 0.01:
            action = "Battery supplies house"
        else:
            action = "Hold — no battery export planned"
        result[slot["valid_from"]] = {
            "action": action,
            "estimated_soc_percent": None,
            "basis": "advisory published Agile schedule; physical guard controls actual dispatch",
            "reporting_only": True,
            "advisory": True,
        }
    return result


def _observed_foxess_soc(coordinator: Any) -> float | None:
    """Publish *observed* physical SOC, never a replayed or simulated forecast."""
    data = getattr(coordinator, "data", None)
    snapshot = getattr(data, "snapshot", None)
    if snapshot is None:
        return None
    now = datetime.now(UTC)
    observed_at = getattr(snapshot, "timestamp", None)
    if (
        not isinstance(observed_at, datetime)
        or observed_at.tzinfo is None
        or not timedelta(0) <= now - observed_at <= timedelta(seconds=120)
    ):
        return None
    stale_fields = getattr(snapshot, "stale_fields", ())
    if "battery_soc" in (stale_fields or ()):
        return None
    source_ages = getattr(snapshot, "source_age_seconds", {})
    age = (
        _finite_nonnegative(source_ages.get("battery_soc"))
        if isinstance(source_ages, dict)
        else None
    )
    max_age = _finite_nonnegative(
        getattr(
            getattr(getattr(coordinator, "settings", None), "control", None),
            "stale_data_seconds",
            None,
        )
    )
    if age is None or max_age is None or age > max_age:
        return None
    soc = _finite_nonnegative(getattr(snapshot, "battery_soc", None))
    return round(soc, 1) if soc is not None and soc <= 100 else None


def _attributes(coordinator: Any) -> dict[str, Any]:
    """Return the slot payload used by the rebuilt dashboard and Pi/Web."""
    state = _agile_state(coordinator)
    quality = state.get("price_quality")
    if not isinstance(quality, dict):
        quality = {}

    today_slots = _presentation_slots(state.get("today_slots"))
    tomorrow_slots = _presentation_slots(state.get("tomorrow_slots"))
    live_outlook = _physical_live_slot_outlook(coordinator, state)
    advisory_outlook = _advisory_live_slot_outlook(state) if not live_outlook else {}

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
        "published_plan_slot_outlook": advisory_outlook,
        "published_plan_slot_outlook_available": bool(advisory_outlook),
        "observed_foxess_soc_percent": _observed_foxess_soc(coordinator),
        "physical_live_slot_outlook_basis": (
            next(iter(live_outlook.values())).get("basis")
            if live_outlook
            else "unavailable: verified chronological physical SOC path absent or stale"
        ),
        "physical_live_slot_outlook_current_soc_percent": (
            state.get("rolling_export_plan", {}).get("planning_soc_percent")
            if isinstance(state.get("rolling_export_plan"), dict)
            and state["rolling_export_plan"].get("planning_soc_source")
            == "verified FoxESS physical lower bound"
            else None
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
