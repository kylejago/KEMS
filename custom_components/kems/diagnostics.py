"""Diagnostics support for KEMS."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .commissioning import build_commissioning_snapshot
from .coordinator import KEMSCoordinator
from .panel import panel_health_snapshot
from .providers.octopus import DEFAULT_INTELLIGENT_STALE_DATA_SECONDS
from .update_orchestrator import update_orchestrator_snapshot


def _state_payload(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """Return compact state metadata for diagnostics."""
    state = hass.states.get(entity_id)
    if state is None:
        return {"state": None, "available": False}
    last_reported = getattr(state, "last_reported", None) or state.last_updated
    report_age = max((dt_util.now() - last_reported).total_seconds(), 0.0)
    return {
        "state": state.state,
        "available": state.state not in {"unknown", "unavailable"},
        "unit": state.attributes.get("unit_of_measurement"),
        "device_class": state.attributes.get("device_class"),
        "state_class": state.attributes.get("state_class"),
        "friendly_name": state.attributes.get("friendly_name"),
        "last_updated": state.last_updated.isoformat(),
        "last_reported": last_reported.isoformat(),
        "report_age_seconds": round(report_age, 1),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return a complete non-secret KEMS diagnostic snapshot."""
    coordinator: KEMSCoordinator = entry.runtime_data
    data = coordinator.data
    configured = coordinator.entities.as_dict()
    source_states = {
        logical_name: {
            "entity_id": entity_id,
            **_state_payload(hass, entity_id),
        }
        for logical_name, entity_id in sorted(configured.items())
    }

    registry = er.async_get(hass)
    kems_entities: dict[str, Any] = {}
    for registry_entry in registry.entities.values():
        if registry_entry.config_entry_id != entry.entry_id:
            continue
        kems_entities[registry_entry.entity_id] = _state_payload(
            hass,
            registry_entry.entity_id,
        )

    return {
        "integration": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "version": entry.version,
            "minor_version": entry.minor_version,
        },
        "configured_entities": configured,
        "source_validation": {
            "valid": coordinator.source_validation.valid,
            "accepted": dict(sorted(coordinator.source_validation.accepted.items())),
            "rejected": dict(sorted(coordinator.source_validation.rejected.items())),
            "summary": coordinator.source_validation.summary(),
        },
        "source_entity_states": source_states,
        "source_freshness": {
            "stale_timeout_seconds": coordinator.settings.control.stale_data_seconds,
            "intelligent_source_stale_timeout_seconds": max(
                coordinator.settings.control.stale_data_seconds,
                DEFAULT_INTELLIGENT_STALE_DATA_SECONDS,
            ),
            "max_dynamic_source_age_seconds": (data.snapshot.source_data_age_seconds),
            "stale_fields": list(data.snapshot.stale_fields),
            "dynamic_field_ages_seconds": dict(
                sorted(data.snapshot.source_age_seconds.items())
            ),
            "max_tariff_source_age_seconds": (
                data.snapshot.tariff_source_data_age_seconds
            ),
            "tariff_stale_fields": list(data.snapshot.tariff_stale_fields),
            "tariff_field_ages_seconds": dict(
                sorted(data.snapshot.tariff_source_age_seconds.items())
            ),
            "intelligent_slot_source_fresh": (
                data.snapshot.intelligent_slot_source_fresh
            ),
            "cheap_period_confirmed": data.snapshot.cheap_period_confirmed,
        },
        "kems_entity_states": dict(sorted(kems_entities.items())),
        "options": dict(entry.options),
        "phase": data.phase,
        "snapshot": data.snapshot.to_dict(),
        "grid_diagnostics": {
            "raw_import_kw": data.snapshot.raw_grid_import_kw,
            "raw_export_kw": data.snapshot.raw_grid_export_kw,
            "normalised_import_kw": data.snapshot.grid_import_kw,
            "normalised_export_kw": data.snapshot.grid_export_kw,
            "normalisation_mode": data.snapshot.grid_flow_mode,
            "signed_net_kw": (
                None
                if data.snapshot.grid_import_kw is None
                and data.snapshot.grid_export_kw is None
                else round(
                    (data.snapshot.grid_import_kw or 0.0)
                    - (data.snapshot.grid_export_kw or 0.0),
                    3,
                )
            ),
            "sign_convention": "positive = import, negative = export",
        },
        "learning": asdict(data.learned),
        "gas": asdict(data.gas),
        "advice": {
            "primary": data.advice.primary.to_dict(),
            "items": [item.to_dict() for item in data.advice.items],
        },
        "simulation": asdict(data.simulation),
        "agile_smart_export": coordinator.agile_smart_export_state,
        "forecast": data.forecast.to_dict(),
        "forecast_plan": data.forecast_plan.to_dict(),
        "forecast_validation": coordinator.forecast_validation_state.to_dict(),
        "forecast_validation_observations": [
            item.to_dict() for item in coordinator.forecast_validation_observations
        ],
        "scenarios": data.scenarios.to_dict(),
        "whole_home": asdict(data.whole_home),
        "lifetime": data.lifetime.to_dict(),
        "periods": {
            period_name: totals.to_dict()
            for period_name, totals in data.periods.items()
        },
        "roi": asdict(data.roi),
        "control": asdict(data.control),
        "commissioning": build_commissioning_snapshot(hass, coordinator),
        "panel_health": panel_health_snapshot(hass),
        "updates": update_orchestrator_snapshot(hass, entry),
        "last_power_down": data.last_power_down.to_dict(),
        "quality": asdict(data.quality),
        "history_samples": data.history_samples,
        "last_update_success": coordinator.last_update_success,
        "last_exception": (
            str(last_exception)
            if (last_exception := getattr(coordinator, "last_exception", None))
            is not None
            else None
        ),
    }
