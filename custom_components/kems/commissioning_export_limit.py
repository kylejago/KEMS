"""Fail-closed FoxESS export-limit commissioning proof."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .foxess_command_shadow import build_foxess_command_shadow_snapshot

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import KEMSCoordinator

PASS = "PASS"
WAIT = "WAIT"
FAIL = "FAIL"


def _check(status: str, detail: str) -> dict[str, Any]:
    """Return the required export-limit commissioning checklist item."""
    return {
        "key": "foxess_export_limit_readback",
        "label": "FoxESS export-limit readback",
        "status": status,
        "detail": detail,
        "required": True,
    }


def assess_foxess_export_limit_readback(
    *,
    configured_export_limit_kw: object,
    selected_device_id: object,
    binding: Mapping[str, object] | None,
    observed_export_limit_w: object,
) -> dict[str, Any]:
    """Assess one reviewed FoxESS export-limit sensor against the DNO ceiling."""
    try:
        configured_kw = float(configured_export_limit_kw)
    except (TypeError, ValueError):
        return _check(FAIL, "Configured KEMS/DNO export ceiling is not numeric")
    if configured_kw <= 0:
        return _check(
            FAIL,
            f"Configured KEMS/DNO export ceiling is invalid: {configured_kw} kW",
        )

    if not selected_device_id:
        return _check(
            WAIT,
            "Waiting for one authoritative FoxESS telemetry device before proving the export limit",
        )

    binding_data = dict(binding or {})
    if binding_data.get("status") != PASS:
        candidates = binding_data.get("candidate_readback_entity_ids") or []
        detail = "Waiting for one usable FoxESS export-limit command/readback binding"
        if candidates:
            detail += f"; candidates={list(candidates)}"
        return _check(WAIT, detail)

    readback_entity_id = binding_data.get("readback_entity_id")
    observation_source = binding_data.get("observation_source")
    if not readback_entity_id or observation_source != "sensor_readback":
        return _check(
            WAIT,
            "Waiting for the dedicated read-only FoxESS export-limit sensor readback",
        )

    try:
        observed_w = float(observed_export_limit_w)
    except (TypeError, ValueError):
        return _check(
            WAIT,
            f"FoxESS export-limit readback is unavailable or non-numeric: {readback_entity_id}",
        )

    if observed_w < 0:
        return _check(
            FAIL,
            f"{readback_entity_id}: observed export limit is invalid: {observed_w} W",
        )

    configured_w = configured_kw * 1000.0
    tolerance_w = 1.0
    if observed_w > configured_w + tolerance_w:
        return _check(
            FAIL,
            (
                f"{readback_entity_id}: observed={observed_w / 1000.0:.3f} kW exceeds "
                f"configured/DNO ceiling={configured_kw:.3f} kW"
            ),
        )

    return _check(
        PASS,
        (
            f"{readback_entity_id}: observed={observed_w / 1000.0:.3f} kW; "
            f"configured/DNO ceiling={configured_kw:.3f} kW"
        ),
    )


def build_foxess_export_limit_readback_check(
    hass: HomeAssistant,
    coordinator: KEMSCoordinator,
    *,
    configured_export_limit_kw: object,
) -> dict[str, Any]:
    """Use the exact Shadow binding/readback path for commissioning proof."""
    shadow = build_foxess_command_shadow_snapshot(hass, coordinator)
    entity_binding = shadow.get("entity_binding")
    binding_root = dict(entity_binding) if isinstance(entity_binding, Mapping) else {}
    entities = binding_root.get("entities")
    binding_entities = dict(entities) if isinstance(entities, Mapping) else {}
    export_binding = binding_entities.get("export_power_limit")
    export_binding_data = (
        dict(export_binding) if isinstance(export_binding, Mapping) else None
    )
    observed_state = shadow.get("observed_foxess_state")
    observed = dict(observed_state) if isinstance(observed_state, Mapping) else {}

    return assess_foxess_export_limit_readback(
        configured_export_limit_kw=configured_export_limit_kw,
        selected_device_id=binding_root.get("selected_device_id"),
        binding=export_binding_data,
        observed_export_limit_w=observed.get("export_power_limit_w"),
    )
