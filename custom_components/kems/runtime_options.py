"""Helpers for safe runtime option changes from KEMS control-lab entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CONTROL_ENABLED,
    CONF_OHME_EXTRA_SLOT_TARIFF,
    CONF_OHME_PRIORITISE_SAVINGS,
    CONF_SYSTEM_COMMISSIONED,
    OHME_EXTRA_SLOT_TARIFF_LABELS,
)
from .settings import KEMSSettings


async def async_set_runtime_options(
    hass: HomeAssistant,
    entry: ConfigEntry,
    changes: Mapping[str, Any],
) -> None:
    """Persist related options and reload KEMS once so engines see them atomically."""
    options = {**dict(entry.options), **dict(changes)}
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_set_runtime_option(
    hass: HomeAssistant,
    entry: ConfigEntry,
    key: str,
    value: Any,
) -> None:
    """Persist one option and reload KEMS so every engine sees it atomically."""
    await async_set_runtime_options(hass, entry, {key: value})


async def async_set_ohme_preference_option(
    hass: HomeAssistant,
    entry: ConfigEntry,
    key: str,
    value: Any,
) -> None:
    """Persist operator declarations without reloading commissioned control.

    No live tariff or physical charging code consumes these options in alpha9.237.
    """
    if key == CONF_OHME_PRIORITISE_SAVINGS:
        if not isinstance(value, bool):
            raise ValueError("Ohme savings preference must be a boolean")
    elif key == CONF_OHME_EXTRA_SLOT_TARIFF:
        if value not in OHME_EXTRA_SLOT_TARIFF_LABELS:
            raise ValueError("Unsupported Ohme extra-slot tariff treatment")
    else:
        raise ValueError(f"{key!r} is not an Ohme preference option")
    hass.config_entries.async_update_entry(
        entry, options={**dict(entry.options), key: value}
    )


_CONTROL_GATE_KEYS = frozenset({CONF_CONTROL_ENABLED, CONF_SYSTEM_COMMISSIONED})


async def async_set_control_gate_option(
    hass: HomeAssistant,
    coordinator: Any,
    key: str,
    value: bool,
) -> None:
    """Persist a control opt-in without reloading and discarding live proof.

    Commissioning evidence is deliberately scoped to the current coordinator
    session. The two explicit user-control gates therefore update only their
    persisted option plus the in-memory ControlConfig, then request one normal
    coordinator refresh. Other runtime options continue to use the reload helper.
    """
    if key not in _CONTROL_GATE_KEYS:
        raise ValueError(f"{key!r} is not a KEMS control-gate option")

    entry = coordinator.entry
    options = {**dict(entry.options), key: bool(value)}
    hass.config_entries.async_update_entry(entry, options=options)

    next_settings = KEMSSettings.from_options(options)
    coordinator.settings = replace(
        coordinator.settings,
        control=next_settings.control,
    )
    await coordinator.async_request_refresh()
