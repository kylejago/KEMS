"""Stable Home Assistant state for the customer-facing Agile slot table."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

ENTITY_ID = "sensor.kems_agile_slots"


def _agile_state(coordinator: Any) -> dict[str, Any]:
    """Return the retained Agile state as a normal dictionary."""
    value = getattr(coordinator, "agile_smart_export_state", None)
    return value if isinstance(value, dict) else {}


def _attributes(coordinator: Any) -> dict[str, Any]:
    """Return the slot payload used by the rebuilt dashboard."""
    state = _agile_state(coordinator)
    quality = state.get("price_quality")
    if not isinstance(quality, dict):
        quality = {}

    today_slots = state.get("today_slots")
    tomorrow_slots = state.get("tomorrow_slots")
    if not isinstance(today_slots, list):
        today_slots = []
    if not isinstance(tomorrow_slots, list):
        tomorrow_slots = []

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
