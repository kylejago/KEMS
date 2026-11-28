"""Diagnostics support for KEMS."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .commissioning import (
    build_commissioning_snapshot,
    commissioning_operator_state,
)
from .coordinator import KEMSCoordinator
from .foxess_command_shadow import build_foxess_command_shadow_snapshot
from .foxess_modbus_contract import foxess_modbus_contract_snapshot
from .happy_hour_accounting_diagnostics import build_happy_hour_accounting_audit
from .happy_hour_auto_join import happy_hour_auto_join_state
from .kems_core.agile_plan_budget_reconciliation import reconcile_agile_budget
from .kems_core.diagnostic_evidence import (
    actual_export_evidence,
    agile_current_export_execution_observation,
    agile_export_interval_audit,
    corroborated_unchanged_sources,
    reward_settlement_evidence,
)
from .kems_core.historical_scope import commissioning_history_scope
from .kems_core.history_gap_provenance import history_gap_provenance
from .kems_core.meter_gap_anchor_evidence import meter_gap_anchor_evidence
from .kems_core.operational_diagnostic_probes import (
    foxess_import_counter_candidate_probe,
    power_down_baseline_probe,
    roi_recorder_probe,
)
from .kems_core.period_coverage_probe import observation_coverage_probe
from .kems_core.supplier_charges import historical_reporting_what_if
from .ohme_extra_slot_policy import ohme_extra_slot_evidence
from .panel import panel_health_snapshot
from .product_types import (
    EXPORT_TARIFF_TYPE_AGILE,
    export_tariff_type_from_options,
)
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


def _shadow_validation_state(coordinator: KEMSCoordinator) -> dict[str, Any]:
    """Return alpha7.19+ persistent shadow-validation evidence."""
    recorder = getattr(coordinator, "_shadow_validation", None)
    state = getattr(recorder, "state", {}) if recorder is not None else {}
    return dict(state) if isinstance(state, dict) else {}


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

    # Solar shadow is an advisory HA observation, not a physical command.
    # Its independent manager cache makes missing or failed evaluations explicit.
    agile_state = coordinator.agile_smart_export_state
    solar_shadow = agile_state.get("solar_routing_shadow")
    solar_sensor = _state_payload(hass, "sensor.kems_solar_routing_shadow")

    registry = er.async_get(hass)
    baseline_entity_registry = {
        logical: power_down_baseline_probe(
            configured.get(logical),
            (
                registry.entities.get(configured[logical])
                if configured.get(logical)
                else None
            ),
            hass.states.get(configured[logical]) if configured.get(logical) else None,
        )
        for logical in (
            "saving_session_import_baseline",
            "saving_session_export_baseline",
        )
    }
    # These are historical *candidate* FoxESS energy counters, not authority.
    # Never auto-configure or use them to extend a free-import reward budget.
    import_power_entity = configured.get("grid_import_kw", "")
    candidate_ids = {
        "lifetime_total": import_power_entity + "_energy_total",
        "daily_total": import_power_entity + "_energy_today",
    }
    import_counter_candidates = foxess_import_counter_candidate_probe(
        source_entity_id=import_power_entity,
        source_registry=registry.entities.get(import_power_entity),
        candidates={
            label: (
                registry.entities.get(candidate_id),
                hass.states.get(candidate_id),
            )
            for label, candidate_id in candidate_ids.items()
        },
        now=dt_util.now(),
    )
    reward_state = hass.states.get("sensor.kems_roi_reward_audit")
    reward_recorder = roi_recorder_probe(
        data.roi.reward_audit,
        reward_state.attributes if reward_state is not None else None,
    )
    kems_entities: dict[str, Any] = {}
    for registry_entry in registry.entities.values():
        if registry_entry.config_entry_id != entry.entry_id:
            continue
        kems_entities[registry_entry.entity_id] = _state_payload(
            hass,
            registry_entry.entity_id,
        )

    commissioning = build_commissioning_snapshot(hass, coordinator)
    # One evidence snapshot for both diagnostic sections. Display the same
    # operator readiness as the HA sensor without changing the source gate.
    evidence_state = commissioning.get("state")
    operator_state = commissioning_operator_state(commissioning, data.control)
    commissioning = {
        **commissioning,
        "evidence_state": evidence_state,
        "state": operator_state,
        "operator_display_state": operator_state,
        "operator_state_reporting_only": True,
    }
    shadow_validation = _shadow_validation_state(coordinator)
    shadow_readiness = {
        "digital_twin_ready": bool(shadow_validation.get("ready_for_shadow")),
        "digital_twin_status": shadow_validation.get("status"),
        "hardware_shadow_ready": bool(commissioning.get("ready_for_shadow")),
        "hardware_status": operator_state,
        "hardware_evidence_status": evidence_state,
        "maximum_allowed_hardware_stage": commissioning.get("maximum_allowed_stage"),
        "real_hardware_writes": commissioning.get(
            "real_hardware_writes",
            "blocked",
        ),
        "real_backend_available": bool(data.control.real_backend_available),
        "ready_for_control": bool(commissioning.get("ready_for_control")),
        "meaning": (
            "Digital-twin shadow validates desired commands against simulation; "
            "hardware shadow additionally requires commissioned FoxESS mappings."
        ),
    }

    # Diagnostics should be compact: the recorder retains up to 960 full
    # EV transition samples for safety investigations, but the default JSON
    # export needs only the latest 64. Never delete underlying trace history.
    ev_trace = dict(coordinator.ev_charge_trace_state)
    ev_trace_samples = list(ev_trace.get("samples") or ())
    ev_trace["samples"] = ev_trace_samples[-64:]
    ev_trace["samples_included"] = len(ev_trace["samples"])
    ev_trace["samples_omitted"] = max(
        len(ev_trace_samples) - ev_trace["samples_included"], 0
    )

    offpeak_entity = configured.get("off_peak")
    offpeak_state = hass.states.get(offpeak_entity) if offpeak_entity else None
    offpeak_attrs = offpeak_state.attributes if offpeak_state is not None else {}
    offpeak_boundaries = {
        key: str(offpeak_attrs[key])
        for key in ("current_start", "current_end", "next_start", "next_end")
        if offpeak_attrs.get(key) is not None
    }

    ohme_mode_state = _state_payload(hass, configured.get("ohme_charge_mode", ""))
    ohme_status_state = _state_payload(hass, configured.get("ev_status", ""))
    ohme_power_state = _state_payload(hass, configured.get("ev_power_kw", ""))
    extra_slot_policy = ohme_extra_slot_evidence(
        entry.options,
        charge_mode=ohme_mode_state.get("state"),
        charger_status=ohme_status_state.get("state"),
        charging_power_kw=ohme_power_state.get("state"),
        regular_offpeak_state=(
            offpeak_state.state if offpeak_state is not None else None
        ),
        mode_age_seconds=ohme_mode_state.get("report_age_seconds"),
        status_age_seconds=ohme_status_state.get("report_age_seconds"),
        power_age_seconds=ohme_power_state.get("report_age_seconds"),
    )

    update_snapshot = update_orchestrator_snapshot(hass, entry)
    history_coverage = coordinator._lifetime.historical_coverage_audit
    gap_sources = observation_coverage_probe(
        coordinator._history.records, dt_util.now()
    )
    gap_provenance = history_gap_provenance(
        records=coordinator._history.records,
        update_history=update_snapshot.get("history"),
        lifecycle_events=coordinator._lifecycle_evidence.events,
        ledger_audit=history_coverage,
        now=dt_util.now(),
    )

    gap_meter_anchors = meter_gap_anchor_evidence(
        gaps=gap_provenance["source_gap_details"],
        import_lifetime_rows=coordinator._counter_evidence.lifetime_counter_rows,
        export_lifetime_rows=(
            coordinator._export_counter_evidence.lifetime_counter_rows
        ),
    )

    financial_reconciliation = coordinator._supplier_intervals.financial_reconciliation(
        coordinator._lifetime.completed_daily_meter_totals,
        now=dt_util.now(),
        commissioning_date=coordinator.settings.roi.commissioning_date,
        include_daily_audit=True,
    )
    financial_reconciliation["reporting_what_if"] = historical_reporting_what_if(
        coordinator._lifetime.completed_daily_financial_totals,
        financial_reconciliation["historical_adjustment_preview"],
        data.lifetime,
        data.periods,
        reward_audit=data.roi.reward_audit,
    )

    return {
        "integration": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "version": entry.version,
            "minor_version": entry.minor_version,
        },
        "configured_entities": configured,
        "ohme_charge_plan_observer": coordinator._ohme_charge_plan.status,
        "ohme_extra_slot_policy": extra_slot_policy,
        "octopus_source_consolidation": {
            "tariff_provider": "octopus_energy",
            "regular_offpeak_entity": offpeak_entity,
            "regular_offpeak_state": (
                offpeak_state.state if offpeak_state is not None else None
            ),
            "offpeak_boundaries_reporting_only": offpeak_boundaries,
            "deprecated_intelligent_mappings_present": any(
                key in configured
                for key in ("intelligent_slot", "next_offpeak_start", "offpeak_end")
            ),
            "ohme_extra_daytime_discount": (
                "ev_only_policy_declared_session_unsettled"
                if extra_slot_policy["supplier_policy_declared_ev_only"]
                else "not_supplier_confirmed_fail_closed"
            ),
            "ohme_charge_plan_proves_discount": False,
            "extra_daytime_grid_force_charge_authorised": False,
            "other_integration_uninstall_automated": False,
        },
        "source_validation": {
            "valid": coordinator.source_validation.valid,
            "accepted": dict(sorted(coordinator.source_validation.accepted.items())),
            "rejected": dict(sorted(coordinator.source_validation.rejected.items())),
            "summary": coordinator.source_validation.summary(),
        },
        "source_entity_states": source_states,
        "power_down_baseline_entity_registry": baseline_entity_registry,
        "roi_reward_recorder_probe": reward_recorder,
        "happy_hour_import_counter_candidates": import_counter_candidates,
        "foxess_import_counter_longitudinal_evidence": (
            coordinator._counter_evidence.status
        ),
        "foxess_export_counter_longitudinal_evidence": (
            coordinator._export_counter_evidence.status
        ),
        "historical_two_way_meter_gap_anchors": gap_meter_anchors,
        "supplier_interval_recovery": coordinator._supplier_intervals.status,
        "supplier_electricity_reconciliation": (
            coordinator._supplier_intervals.electricity_reconciliation(
                coordinator._lifetime.completed_daily_meter_totals, now=dt_util.now()
            )
        ),
        "provisional_gas_reconciliation": (
            coordinator._supplier_intervals.provisional_gas_reconciliation(
                coordinator._history.records, now=dt_util.now()
            )
        ),
        "supplier_financial_reconciliation": financial_reconciliation,
        "late_power_down_supplier_evidence": (
            coordinator._supplier_intervals.late_power_down_evidence
        ),
        "commissioning_history_scope": commissioning_history_scope(
            configured_date=entry.options.get("commissioning_date"),
            records=coordinator._history.records,
            now=dt_util.now(),
        ),
        "whatsapp_notifications": (
            coordinator._kems_whatsapp_reporter.status
            if getattr(coordinator, "_kems_whatsapp_reporter", None) is not None
            else {"enabled": False, "status": "not_initialised"}
        ),
        "solar_routing_shadow_continuity": {
            "status": (
                solar_shadow.get("status")
                if isinstance(solar_shadow, dict)
                else "missing_cached_observation"
            ),
            "generated_at": (
                solar_shadow.get("generated_at")
                if isinstance(solar_shadow, dict)
                else None
            ),
            "last_error_type": (
                solar_shadow.get("error_type")
                if isinstance(solar_shadow, dict)
                else None
            ),
            "manager_cache_present": isinstance(solar_shadow, dict),
            "ha_sensor": solar_sensor,
            "ha_state_matches_cached_status": (
                isinstance(solar_shadow, dict)
                and solar_sensor.get("state") == solar_shadow.get("status")
            ),
            "scope": "reporting_only",
            "hardware_writes": "forbidden",
        },
        "source_freshness": {
            "stale_timeout_seconds": coordinator.settings.control.stale_data_seconds,
            "intelligent_source_stale_timeout_seconds": max(
                coordinator.settings.control.stale_data_seconds,
                DEFAULT_INTELLIGENT_STALE_DATA_SECONDS,
            ),
            "max_dynamic_source_age_seconds": (data.snapshot.source_data_age_seconds),
            "stale_fields": list(data.snapshot.stale_fields),
            **corroborated_unchanged_sources(
                data.snapshot.source_age_seconds,
                data.snapshot.stale_fields,
                coordinator.settings.control.stale_data_seconds,
            ),
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
        "shared_bus_ev_balance": dict(data.snapshot.shared_bus_ev_audit),
        "shared_bus_ev_evidence": coordinator.shared_bus_ev_evidence,
        "ev_charge_trace": ev_trace,
        "ev_grid_hold_session": coordinator.ev_grid_hold_state,
        "ev_soc_sync": coordinator.ev_soc_sync_state,
        "control_event_refresh": coordinator.control_event_refresh_state,
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
        "foxess_modbus_contract": foxess_modbus_contract_snapshot(),
        "foxess_command_shadow": build_foxess_command_shadow_snapshot(
            hass,
            coordinator,
        ),
        "foxess_control": coordinator.foxess_control_state,
        "coordinator_performance": coordinator.coordinator_performance_state,
        "restart_service_call": coordinator.restart_service_call_state,
        "core_lifecycle_evidence": coordinator.lifecycle_evidence_state,
        "agile_historical_replay_cache": {
            **coordinator._agile_smart_export._historical_replay_cache.status,
            "historical_summary_path": getattr(
                coordinator._agile_smart_export,
                "_historical_summary_path",
                "not_evaluated",
            ),
            "day_rate_index_builds": getattr(
                coordinator._agile_smart_export, "_day_rate_index_builds", 0
            ),
            "indexed_price_days": len(
                getattr(coordinator._agile_smart_export, "_day_rate_index", {})
            ),
        },
        "export_commissioning_test": coordinator.export_commissioning_test_state,
        "learning": asdict(data.learned),
        "gas": asdict(data.gas),
        "advice": {
            "primary": data.advice.primary.to_dict(),
            "items": [item.to_dict() for item in data.advice.items],
        },
        "simulation": asdict(data.simulation),
        "actual_export_evidence": actual_export_evidence(
            data.simulation.actual_grid_export_kwh,
            data.simulation.actual_export_income_pence,
        ),
        "agile_export_interval_audit": (
            agile_export_interval_audit(
                records=coordinator._history.records,
                agile_state=agile_state,
                now=dt_util.now(),
                reported_grid_export_kwh=data.simulation.actual_grid_export_kwh,
                reported_income_pence=data.simulation.actual_export_income_pence,
                completed_power_down=data.last_power_down.to_dict(),
                activation_cutoff=entry.options.get(
                    "paid_export_accounting_started_at"
                ),
            )
            if export_tariff_type_from_options(entry.options)
            == EXPORT_TARIFF_TYPE_AGILE
            else {"status": "not_agile_tariff", "reporting_only": True}
        ),
        "agile_current_export_execution_observation": (
            agile_current_export_execution_observation(
                snapshot=data.snapshot,
                control=data.control,
                agile_state=agile_state,
                physical_guard=getattr(coordinator, "_agile_live_reserve_status", {}),
            )
            if export_tariff_type_from_options(entry.options)
            == EXPORT_TARIFF_TYPE_AGILE
            else {"status": "not_agile_tariff", "reporting_only": True}
        ),
        "reward_settlement_evidence": reward_settlement_evidence(data.roi.reward_audit),
        "agile_smart_export": agile_state,
        "agile_physical_export_reserve": getattr(
            coordinator, "_agile_live_reserve_status", {"status": "not_yet_evaluated"}
        ),
        "agile_budget_reconciliation": reconcile_agile_budget(
            agile_state,
            getattr(
                coordinator,
                "_agile_live_reserve_status",
                {"status": "not_yet_evaluated"},
            ),
        ),
        "agile_physical_energy_evidence": (
            coordinator._paid_agile_energy_evidence.as_dict()
            if coordinator._paid_agile_energy_evidence is not None
            else {"status": "not_yet_observed"}
        ),
        "happy_hour_auto_join": happy_hour_auto_join_state(coordinator),
        "happy_hour_preparation_dispatch": getattr(
            coordinator, "_happy_hour_preparation_dispatch", {}
        ),
        "happy_hour_import_ledger": coordinator._happy_hour_import_ledger.status,
        "happy_hour_accounting_audit": build_happy_hour_accounting_audit(
            coordinator._happy_hour_import_ledger.status,
            coordinator._lifetime.happy_hour_verified_receipts,
            roi_reward_audit=data.roi.reward_audit,
        ),
        "happy_hour_ohme_control": coordinator.happy_hour_ohme_control_state,
        "agile_history_backfill": coordinator.agile_history_backfill_state,
        "forecast": data.forecast.to_dict(),
        "forecast_plan": data.forecast_plan.to_dict(),
        "forecast_validation": coordinator.forecast_validation_state.to_dict(),
        "forecast_validation_observations": [
            item.to_dict() for item in coordinator.forecast_validation_observations
        ],
        "scenarios": data.scenarios.to_dict(),
        "whole_home": asdict(data.whole_home),
        "lifetime": data.lifetime.to_dict(),
        "roi_reward_audit": data.roi.reward_audit,
        "historical_tariff_revaluation": (
            coordinator._lifetime.historical_tariff_revaluation_status
        ),
        "periods": {
            period_name: totals.to_dict()
            for period_name, totals in data.periods.items()
        },
        "historical_coverage_audit": history_coverage,
        "historical_observation_coverage_causes": gap_sources,
        "historical_restart_gap_provenance": gap_provenance,
        "roi": asdict(data.roi),
        "control": asdict(data.control),
        "alpha969_shadow_plan": dict(data.alpha969_shadow_plan),
        "shadow_validation": shadow_validation,
        "shadow_readiness": shadow_readiness,
        "commissioning": commissioning,
        "panel_health": panel_health_snapshot(hass),
        "updates": update_snapshot,
        "last_power_down": data.last_power_down.to_dict(),
        "quality": asdict(data.quality),
        "history_samples": data.history_samples,
        "history_persistence": coordinator.history_persistence_state,
        "last_update_success": coordinator.last_update_success,
        "last_exception": (
            str(last_exception)
            if (last_exception := getattr(coordinator, "last_exception", None))
            is not None
            else None
        ),
    }
