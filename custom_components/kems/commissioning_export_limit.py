"""Fail-closed FoxESS/KEMS export-ceiling commissioning proof."""

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


def _check(
    status: str,
    detail: str,
    *,
    kems_export_limit_kw: float | None = None,
    foxess_hardware_limit_kw: float | None = None,
    effective_export_limit_kw: float | None = None,
) -> dict[str, Any]:
    """Return the required export-ceiling commissioning checklist item."""
    return {
        "key": "foxess_export_limit_readback",
        "label": "FoxESS / KEMS export ceilings",
        "status": status,
        "detail": detail,
        "required": True,
        "kems_export_limit_kw": kems_export_limit_kw,
        "foxess_hardware_limit_kw": foxess_hardware_limit_kw,
        "effective_export_limit_kw": effective_export_limit_kw,
    }


def assess_foxess_export_limit_readback(
    *,
    configured_export_limit_kw: object,
    selected_device_id: object,
    binding: Mapping[str, object] | None,
    observed_export_limit_w: object,
) -> dict[str, Any]:
    """Prove the KEMS user ceiling does not exceed the live FoxESS ceiling."""
    try:
        kems_kw = float(configured_export_limit_kw)
    except (TypeError, ValueError):
        return _check(FAIL, "Configured KEMS export ceiling is not numeric")
    if kems_kw < 0:
        return _check(
            FAIL,
            f"Configured KEMS export ceiling is invalid: {kems_kw} kW",
            kems_export_limit_kw=kems_kw,
        )

    if not selected_device_id:
        return _check(
            WAIT,
            (
                "Waiting for one authoritative FoxESS telemetry device before "
                "proving the export ceilings"
            ),
            kems_export_limit_kw=kems_kw,
        )

    binding_data = dict(binding or {})
    if binding_data.get("status") != PASS:
        candidates = binding_data.get("candidate_readback_entity_ids") or []
        detail = "Waiting for one usable FoxESS export-limit command/readback binding"
        if candidates:
            detail += f"; candidates={list(candidates)}"
        return _check(WAIT, detail, kems_export_limit_kw=kems_kw)

    readback_entity_id = binding_data.get("readback_entity_id")
    observation_source = binding_data.get("observation_source")
    if not readback_entity_id or observation_source != "sensor_readback":
        return _check(
            WAIT,
            "Waiting for the dedicated read-only FoxESS export-limit sensor readback",
            kems_export_limit_kw=kems_kw,
        )

    try:
        observed_w = float(observed_export_limit_w)
    except (TypeError, ValueError):
        return _check(
            WAIT,
            (
                "FoxESS export-limit readback is unavailable or non-numeric: "
                f"{readback_entity_id}"
            ),
            kems_export_limit_kw=kems_kw,
        )

    if observed_w < 0:
        return _check(
            FAIL,
            f"{readback_entity_id}: observed export limit is invalid: {observed_w} W",
            kems_export_limit_kw=kems_kw,
        )

    foxess_kw = observed_w / 1000.0
    effective_kw = min(kems_kw, foxess_kw)
    tolerance_kw = 0.001

    if kems_kw > foxess_kw + tolerance_kw:
        return _check(
            FAIL,
            (
                f"{readback_entity_id}: KEMS ceiling={kems_kw:.3f} kW exceeds "
                f"FoxESS hardware ceiling={foxess_kw:.3f} kW; "
                f"effective ceiling={effective_kw:.3f} kW"
            ),
            kems_export_limit_kw=kems_kw,
            foxess_hardware_limit_kw=foxess_kw,
            effective_export_limit_kw=effective_kw,
        )

    return _check(
        PASS,
        (
            f"{readback_entity_id}: FoxESS hardware ceiling={foxess_kw:.3f} kW; "
            f"KEMS ceiling={kems_kw:.3f} kW; effective ceiling={effective_kw:.3f} kW"
        ),
        kems_export_limit_kw=kems_kw,
        foxess_hardware_limit_kw=foxess_kw,
        effective_export_limit_kw=effective_kw,
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
