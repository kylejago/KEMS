"""Close completed/current SOC continuity across an active slot after restart.

Alpha8.68/69 backcast completed Today SOC from the settled current battery state.
When legacy elapsed-energy fields are unavailable after a Home Assistant restart,
this final reporting owner can reconstruct the elapsed active-slot battery delta
from KEMS' persisted Agile shadow decisions. The decision history records target
changes with timestamps, so charge and total-discharge energy can be integrated
piecewise instead of assuming the latest power held for the whole half-hour.

The fallback is reporting-only and fail-closed: it requires bounded decision
coverage, finite non-conflicting targets, and configured charge/discharge limits.
It does not alter optimiser, dispatch, settlement accounting, safety, or hardware
writes.
"""

from __future__ import annotations

from typing import Any

from .agile_flow_total_discharge_parity import (
    TotalDischargeFlowParityAgileSmartExportManager,
    _reconcile_completed_settled_soc,
    _reconcile_future_total_discharge_flow,
)
from .agile_intelligent_dispatch_observability import (
    IntelligentDispatchObservabilityAgileSmartExportManager,
)
from .agile_live_solar_soc_continuity import _dt, _number, _rebase_display_soc
from .kems_core import SimulationConfig

_EPSILON = 1e-6
_POWER_TOLERANCE_KW = 0.05
_INITIAL_DECISION_GRACE_SECONDS = 120.0
_PRIOR_DECISION_MAX_AGE_SECONDS = 300.0


def _decision_target(
    decision: dict[str, Any], config: SimulationConfig
) -> tuple[float, float] | None:
    """Return validated charge/total-discharge kW from one persisted decision."""
    target = decision.get("target")
    if not isinstance(target, dict):
        return None
    charge = _number(target.get("charge_kw"))
    discharge = _number(target.get("total_discharge_kw"))
    if charge is None or discharge is None:
        return None
    charge = max(charge, 0.0)
    discharge = max(discharge, 0.0)
    if charge > _EPSILON and discharge > _EPSILON:
        return None
    if charge > float(config.max_charge_kw) + _POWER_TOLERANCE_KW:
        return None
    if discharge > float(config.max_discharge_kw) + _POWER_TOLERANCE_KW:
        return None
    return charge, discharge


def _integrate_active_decision_energy(
    state: dict[str, Any],
    decisions: list[dict[str, Any]],
    config: SimulationConfig,
) -> dict[str, Any] | None:
    """Integrate persisted target changes over the elapsed active half-hour."""
    routing = state.get("current_routing_snapshot")
    if not isinstance(routing, dict) or not routing.get("available"):
        return None
    active_start = _dt(routing.get("routing_valid_from"))
    active_end = _dt(routing.get("routing_valid_to"))
    generated_at = _dt(routing.get("generated_at"))
    if active_start is None or active_end is None or generated_at is None:
        return None
    elapsed_end = min(generated_at, active_end)
    if active_end <= active_start or elapsed_end <= active_start:
        return None

    parsed: list[tuple[Any, dict[str, Any], tuple[float, float]]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        timestamp = _dt(decision.get("timestamp"))
        target = _decision_target(decision, config)
        if timestamp is None or target is None or timestamp > elapsed_end:
            continue
        parsed.append((timestamp, decision, target))
    parsed.sort(key=lambda item: item[0])
    if not parsed:
        return None

    first_after = next((item for item in parsed if item[0] >= active_start), None)
    prior = next((item for item in reversed(parsed) if item[0] <= active_start), None)
    initial = None
    initial_source = None
    if first_after is not None:
        gap = (first_after[0] - active_start).total_seconds()
        if 0.0 <= gap <= _INITIAL_DECISION_GRACE_SECONDS:
            initial = first_after
            initial_source = "first active-slot decision within startup grace"
    if initial is None and prior is not None:
        age = (active_start - prior[0]).total_seconds()
        if 0.0 <= age <= _PRIOR_DECISION_MAX_AGE_SECONDS:
            initial = prior
            initial_source = "recent decision carried across slot boundary"
    if initial is None:
        return None

    cursor = active_start
    current_target = initial[2]
    stored_delta = 0.0
    charge_input_kwh = 0.0
    discharge_ac_kwh = 0.0
    segments = 0
    decision_count = 0

    for timestamp, _decision, target in parsed:
        if timestamp <= active_start or timestamp > elapsed_end:
            continue
        duration_hours = max((timestamp - cursor).total_seconds(), 0.0) / 3600.0
        if duration_hours > 0.0:
            charge_kw, discharge_kw = current_target
            charge_input_kwh += charge_kw * duration_hours
            discharge_ac_kwh += discharge_kw * duration_hours
            stored_delta += (
                charge_kw * duration_hours * float(config.charge_efficiency)
                - discharge_kw
                * duration_hours
                / max(float(config.discharge_efficiency), _EPSILON)
            )
            segments += 1
        current_target = target
        cursor = timestamp
        decision_count += 1

    duration_hours = max((elapsed_end - cursor).total_seconds(), 0.0) / 3600.0
    if duration_hours > 0.0:
        charge_kw, discharge_kw = current_target
        charge_input_kwh += charge_kw * duration_hours
        discharge_ac_kwh += discharge_kw * duration_hours
        stored_delta += (
            charge_kw * duration_hours * float(config.charge_efficiency)
            - discharge_kw
            * duration_hours
            / max(float(config.discharge_efficiency), _EPSILON)
        )
        segments += 1

    elapsed_seconds = (elapsed_end - active_start).total_seconds()
    if elapsed_seconds <= 0.0 or segments <= 0:
        return None
    return {
        "stored_delta_kwh": stored_delta,
        "charge_input_kwh": charge_input_kwh,
        "discharge_ac_kwh": discharge_ac_kwh,
        "elapsed_seconds": elapsed_seconds,
        "segments": segments,
        "decision_count": decision_count + 1,
        "initial_source": initial_source,
        "active_start": active_start.isoformat(),
        "elapsed_end": elapsed_end.isoformat(),
    }


def _reconcile_completed_from_persisted_decisions(
    state: dict[str, Any],
    *,
    decisions: list[dict[str, Any]],
    now: Any,
    config: SimulationConfig,
) -> int:
    """Retry Alpha8.68 backcast with an explicit persisted-decision anchor."""
    diagnostic = state.get("completed_flow_soc_continuity")
    if not isinstance(diagnostic, dict):
        return 0
    if diagnostic.get("applied"):
        return 0
    if diagnostic.get("reason") != "active elapsed battery energy unavailable":
        return 0

    estimate = _integrate_active_decision_energy(state, decisions, config)
    if estimate is None:
        diagnostic["canonical_decision_elapsed_fallback_used"] = False
        diagnostic["canonical_decision_elapsed_available"] = False
        diagnostic["canonical_decision_elapsed_reason"] = (
            "persisted Agile decision coverage insufficient or invalid"
        )
        return 0

    routing = state.get("current_routing_snapshot")
    routing = routing if isinstance(routing, dict) else {}
    active_start = _dt(routing.get("routing_valid_from"))
    active_end = _dt(routing.get("routing_valid_to"))
    active = next(
        (
            slot
            for slot in state.get("today_slots", []) or []
            if isinstance(slot, dict)
            and _dt(slot.get("valid_from")) == active_start
            and _dt(slot.get("valid_to")) == active_end
        ),
        None,
    )
    if not isinstance(active, dict):
        return 0

    # Alpha8.68's pure backcast helper consumes the historical elapsed fields.
    # Populate them only for this call from the integrated canonical target
    # energy, then restore the row before it is published. Charge is supplied as
    # stored energy because the helper's legacy charge fields represent battery
    # energy; total AC discharge is supplied as synthetic battery export so the
    # existing discharge-efficiency accounting remains authoritative.
    keys = (
        "grid_export_kwh",
        "solar_export_kwh",
        "battery_to_home_kwh",
        "solar_to_battery_kwh",
        "grid_to_battery_kwh",
    )
    saved = {key: (key in active, active.get(key)) for key in keys}
    active["grid_export_kwh"] = max(float(estimate["discharge_ac_kwh"]), 0.0)
    active["solar_export_kwh"] = 0.0
    active["battery_to_home_kwh"] = 0.0
    active["solar_to_battery_kwh"] = 0.0
    active["grid_to_battery_kwh"] = max(float(estimate["stored_delta_kwh"]), 0.0)
    try:
        corrected = _reconcile_completed_settled_soc(state, now=now, config=config)
    finally:
        for key, (present, value) in saved.items():
            if present:
                active[key] = value
            else:
                active.pop(key, None)

    if corrected <= 0:
        diagnostic = state.get("completed_flow_soc_continuity")
        if isinstance(diagnostic, dict):
            diagnostic["canonical_decision_elapsed_fallback_used"] = False
            diagnostic["canonical_decision_elapsed_available"] = True
        return 0

    diagnostic = state.get("completed_flow_soc_continuity")
    if isinstance(diagnostic, dict):
        diagnostic["active_elapsed_battery_delta_kwh"] = round(
            float(estimate["stored_delta_kwh"]), 6
        )
        diagnostic["active_elapsed_battery_delta_source"] = (
            "persisted Agile charge/total-discharge decisions"
        )
        diagnostic["canonical_decision_elapsed_fallback_used"] = True
        diagnostic["canonical_decision_elapsed_available"] = True
        diagnostic["canonical_decision_elapsed_seconds"] = round(
            float(estimate["elapsed_seconds"]), 3
        )
        diagnostic["canonical_decision_elapsed_segments"] = int(estimate["segments"])
        diagnostic["canonical_decision_count"] = int(estimate["decision_count"])
        diagnostic["canonical_decision_initial_source"] = estimate["initial_source"]
        diagnostic["canonical_decision_charge_input_kwh"] = round(
            float(estimate["charge_input_kwh"]), 6
        )
        diagnostic["canonical_decision_discharge_ac_kwh"] = round(
            float(estimate["discharge_ac_kwh"]), 6
        )
        diagnostic["reporting_only"] = True
        diagnostic["hardware_writes"] = "blocked"
    return corrected


class ActiveElapsedSocContinuityAgileSmartExportManager(
    TotalDischargeFlowParityAgileSmartExportManager
):
    """Publish Today SOC with restart-safe active-slot elapsed-energy evidence."""

    def _publish(self, state: dict[str, Any]) -> None:
        # Reproduce the existing final reporting sequence so the persisted
        # decision fallback runs before the underlying publisher snapshots state.
        _reconcile_future_total_discharge_flow(state)
        config = getattr(self, "_rolling_config", None)
        routing = state.get("current_routing_snapshot")
        routing = routing if isinstance(routing, dict) else {}
        now = _dt(routing.get("generated_at"))
        if isinstance(config, SimulationConfig) and now is not None:
            _rebase_display_soc(state, now=now, config=config)
            corrected = _reconcile_completed_settled_soc(
                state,
                now=now,
                config=config,
            )
            if corrected <= 0:
                decisions = getattr(self, "_agile_decisions", None)
                if isinstance(decisions, list):
                    _reconcile_completed_from_persisted_decisions(
                        state,
                        decisions=[item for item in decisions if isinstance(item, dict)],
                        now=now,
                        config=config,
                    )

        # Skip TotalDischargeFlowParityAgileSmartExportManager._publish because
        # its sequence has already run above; continue at its direct parent.
        IntelligentDispatchObservabilityAgileSmartExportManager._publish(self, state)
