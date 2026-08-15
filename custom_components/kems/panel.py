"""Persistent health tracking for the KEMS-managed ESPHome panel."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN

PANEL_CONFIG_VERSION = "0.7.0-alpha7-panel2"
PANEL_HEALTH_STORAGE_VERSION = 1
PANEL_HEALTH_STORAGE_KEY = "kems.panel_health"
PANEL_HEALTH_DATA_KEY = "panel_health"
PANEL_HEALTH_STORE_KEY = "panel_health_store"
PANEL_VERIFY_TIMEOUT_SECONDS = 600
PANEL_VERIFY_INTERVAL_SECONDS = 5


def _default_panel_health() -> dict[str, Any]:
    """Return a complete default managed-panel health payload."""
    return {
        "status": "Unknown",
        "managed": False,
        "automatic_ota_armed": False,
        "expected_version": PANEL_CONFIG_VERSION,
        "reported_version": None,
        "reported_entity_id": None,
        "last_config_sync": None,
        "last_ota_attempt": None,
        "last_ota_success": None,
        "last_ota_result": "never",
        "esphome_job_id": None,
        "last_error": None,
        "updated_at": None,
    }


def _domain_data(hass: HomeAssistant) -> dict[str, Any]:
    """Return KEMS' Home Assistant runtime-data bucket."""
    data = hass.data.setdefault(DOMAIN, {})
    if not isinstance(data, dict):
        data = {}
        hass.data[DOMAIN] = data
    return data


async def async_load_panel_health(hass: HomeAssistant) -> dict[str, Any]:
    """Load retained panel management state once per Home Assistant runtime."""
    domain_data = _domain_data(hass)
    existing = domain_data.get(PANEL_HEALTH_DATA_KEY)
    if isinstance(existing, dict):
        return existing

    store: Store[dict[str, Any]] = Store(
        hass,
        PANEL_HEALTH_STORAGE_VERSION,
        PANEL_HEALTH_STORAGE_KEY,
    )
    saved = await store.async_load()
    state = _default_panel_health()
    if isinstance(saved, dict):
        state.update(saved)
    state["expected_version"] = PANEL_CONFIG_VERSION
    domain_data[PANEL_HEALTH_DATA_KEY] = state
    domain_data[PANEL_HEALTH_STORE_KEY] = store
    return state


def panel_health_snapshot(hass: HomeAssistant) -> dict[str, Any]:
    """Return current panel state without performing I/O."""
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return _default_panel_health()
    state = domain_data.get(PANEL_HEALTH_DATA_KEY)
    if not isinstance(state, dict):
        return _default_panel_health()
    return {**_default_panel_health(), **state}


async def async_update_panel_health(
    hass: HomeAssistant,
    **changes: Any,
) -> dict[str, Any]:
    """Update and persist managed-panel health fields."""
    state = await async_load_panel_health(hass)
    state.update(changes)
    state["expected_version"] = PANEL_CONFIG_VERSION
    state["updated_at"] = dt_util.now().isoformat()

    domain_data = _domain_data(hass)
    store = domain_data.get(PANEL_HEALTH_STORE_KEY)
    if isinstance(store, Store):
        await store.async_save(dict(state))
    return state


def find_panel_firmware_state(hass: HomeAssistant) -> State | None:
    """Find the firmware-version text sensor published by the managed panel."""
    candidates: list[State] = []
    for state in hass.states.async_all("sensor"):
        entity_id = state.entity_id.lower()
        friendly_name = str(state.attributes.get("friendly_name", "")).lower()
        if (
            "panel firmware version" not in friendly_name
            and "panel_firmware_version" not in entity_id
        ):
            continue
        if "kems16x16" in friendly_name or "kems16x16" in entity_id:
            return state
        if "kems" in friendly_name or "kems" in entity_id:
            candidates.append(state)
    return candidates[0] if len(candidates) == 1 else None


async def async_refresh_reported_panel_version(hass: HomeAssistant) -> dict[str, Any]:
    """Refresh the retained firmware version from Home Assistant state."""
    panel_state = find_panel_firmware_state(hass)
    if panel_state is None or panel_state.state in {"unknown", "unavailable"}:
        return await async_load_panel_health(hass)

    current = panel_health_snapshot(hass)
    status = current["status"]
    if panel_state.state == PANEL_CONFIG_VERSION and status not in {
        "Updating",
        "Success",
    }:
        status = "Ready"
    elif panel_state.state != PANEL_CONFIG_VERSION and status not in {
        "Updating",
        "Manual install required",
    }:
        status = "Version mismatch"

    return await async_update_panel_health(
        hass,
        status=status,
        reported_version=panel_state.state,
        reported_entity_id=panel_state.entity_id,
    )


async def async_verify_panel_firmware(
    hass: HomeAssistant,
    *,
    timeout_seconds: int = PANEL_VERIFY_TIMEOUT_SECONDS,
) -> bool:
    """Confirm that the expected firmware reconnects after an automatic OTA."""
    deadline = monotonic() + max(int(timeout_seconds), PANEL_VERIFY_INTERVAL_SECONDS)
    last_reported: str | None = None
    last_entity_id: str | None = None

    while monotonic() < deadline:
        panel_state = find_panel_firmware_state(hass)
        if panel_state is not None and panel_state.state not in {
            "unknown",
            "unavailable",
        }:
            last_reported = panel_state.state
            last_entity_id = panel_state.entity_id
            if panel_state.state == PANEL_CONFIG_VERSION:
                now = dt_util.now().isoformat()
                await async_update_panel_health(
                    hass,
                    status="Success",
                    reported_version=panel_state.state,
                    reported_entity_id=panel_state.entity_id,
                    last_ota_success=now,
                    last_ota_result="success",
                    last_error=None,
                )
                return True
        await asyncio.sleep(PANEL_VERIFY_INTERVAL_SECONDS)

    detail = (
        f"Panel reported {last_reported!r} instead of {PANEL_CONFIG_VERSION!r}"
        if last_reported is not None
        else f"Panel did not report {PANEL_CONFIG_VERSION!r} within {timeout_seconds} seconds"
    )
    await async_update_panel_health(
        hass,
        status="Failed",
        reported_version=last_reported,
        reported_entity_id=last_entity_id,
        last_ota_result="failed",
        last_error=detail,
    )
    return False
