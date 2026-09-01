"""Stable Home Assistant state for the customer-facing Agile slot table."""

from __future__ import annotations

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


def _attributes(coordinator: Any) -> dict[str, Any]:
    """Return the slot payload used by the rebuilt dashboard and Pi/Web."""
    state = _agile_state(coordinator)
    quality = state.get("price_quality")
    if not isinstance(quality, dict):
        quality = {}

    today_slots = _presentation_slots(state.get("today_slots"))
    tomorrow_slots = _presentation_slots(state.get("tomorrow_slots"))

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
