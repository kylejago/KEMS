"""Restart-safe display SOC anchor reconciliation for persisted Agile decisions.

Alpha8.71 proved that recorder-owned persisted Agile decisions survive Home
Assistant restart and can reconstruct active-slot target energy. Live restart
evidence then showed that the settled SOC restored immediately after startup can
still represent the active-slot boundary rather than an elapsed current SOC.
Applying the reconstructed elapsed energy as though that anchor were already
current double-counts the active slot and breaks midnight display continuity.

This final reporting owner uses the persisted midnight rollover seed as an
independent invariant. Only when treating the settled SOC as the active-slot
boundary collapses the rollover residual back inside tolerance does it derive a
temporary display-current SOC, rebase active/future display SOC, and rerun the
completed-row backcast. The routing/optimiser SOC is restored unchanged before
publication. No accounting, dispatch, safety, or hardware-control state changes.
"""

from __future__ import annotations

from typing import Any

from .agile_active_elapsed_soc_continuity import (
    ActiveElapsedSocContinuityAgileSmartExportManager,
    _reconcile_completed_from_persisted_decisions,
)
from .agile_flow_total_discharge_parity import (
    _reconcile_completed_settled_soc,
    _reconcile_future_total_discharge_flow,
)
from .agile_intelligent_dispatch_observability import (
    IntelligentDispatchObservabilityAgileSmartExportManager,
)
from .agile_live_solar_soc_continuity import _dt, _number, _rebase_display_soc
from .kems_core import SimulationConfig

_EPSILON = 1e-6
_ROLLOVER_ANCHOR_TOLERANCE_PERCENT = 0.25


def _restart_boundary_anchor_candidate(
    state: dict[str, Any],
    config: SimulationConfig,
) -> dict[str, float] | None:
    """Return a proven boundary-anchor correction from published fallback evidence."""
    diagnostic = state.get("completed_flow_soc_continuity")
    routing = state.get("current_routing_snapshot")
    if not isinstance(diagnostic, dict) or not isinstance(routing, dict):
        return None
    if diagnostic.get("canonical_decision_elapsed_fallback_used") is not True:
        return None

    residual = _number(diagnostic.get("rollover_residual_percent"))
    stored_delta = _number(diagnostic.get("active_elapsed_battery_delta_kwh"))
    routing_soc = _number(routing.get("simulated_soc_percent"))
    capacity = float(config.battery_capacity_kwh)
    if (
        residual is None
        or stored_delta is None
        or routing_soc is None
        or capacity <= _EPSILON
    ):
        return None

    delta_percent = stored_delta / capacity * 100.0
    candidate_residual = residual + delta_percent
    display_current_soc = routing_soc + delta_percent
    if not (-_EPSILON <= display_current_soc <= 100.0 + _EPSILON):
        return None
    if abs(residual) <= _ROLLOVER_ANCHOR_TOLERANCE_PERCENT:
        return None
    if abs(candidate_residual) > _ROLLOVER_ANCHOR_TOLERANCE_PERCENT:
        return None
    if abs(candidate_residual) >= abs(residual):
        return None

    return {
        "routing_soc_percent": routing_soc,
        "display_current_soc_percent": min(max(display_current_soc, 0.0), 100.0),
        "stored_delta_percent": delta_percent,
        "rollover_residual_before_percent": residual,
        "rollover_residual_candidate_percent": candidate_residual,
    }


def _reconcile_restart_boundary_anchor(
    state: dict[str, Any],
    *,
    now: Any,
    config: SimulationConfig,
) -> int:
    """Rebase display SOC when rollover continuity proves a restart boundary anchor."""
    candidate = _restart_boundary_anchor_candidate(state, config)
    if candidate is None:
        diagnostic = state.get("completed_flow_soc_continuity")
        if isinstance(diagnostic, dict) and diagnostic.get(
            "canonical_decision_elapsed_fallback_used"
        ):
            diagnostic["canonical_decision_soc_anchor_mode"] = "elapsed current SOC"
            diagnostic["canonical_decision_routing_soc_unchanged"] = True
        return 0

    diagnostic = state.get("completed_flow_soc_continuity")
    routing = state.get("current_routing_snapshot")
    if not isinstance(diagnostic, dict) or not isinstance(routing, dict):
        return 0

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

    stored_charge = _number(diagnostic.get("canonical_decision_stored_charge_kwh"))
    discharge_ac = _number(diagnostic.get("canonical_decision_discharge_ac_kwh"))
    if stored_charge is None or discharge_ac is None:
        return 0

    decision_evidence = {
        key: value
        for key, value in diagnostic.items()
        if key.startswith("canonical_decision_")
    }
    active_elapsed_delta = diagnostic.get("active_elapsed_battery_delta_kwh")
    active_elapsed_source = diagnostic.get("active_elapsed_battery_delta_source")

    keys = (
        "grid_export_kwh",
        "solar_export_kwh",
        "battery_to_home_kwh",
        "solar_to_battery_kwh",
        "grid_to_battery_kwh",
    )
    saved = {key: (key in active, active.get(key)) for key in keys}
    routing_soc_present = "simulated_soc_percent" in routing
    routing_soc_saved = routing.get("simulated_soc_percent")
    active["grid_export_kwh"] = max(discharge_ac, 0.0)
    active["solar_export_kwh"] = 0.0
    active["battery_to_home_kwh"] = 0.0
    active["solar_to_battery_kwh"] = 0.0
    active["grid_to_battery_kwh"] = max(stored_charge, 0.0)

    try:
        routing["simulated_soc_percent"] = candidate["display_current_soc_percent"]
        _rebase_display_soc(state, now=now, config=config)
        corrected = _reconcile_completed_settled_soc(state, now=now, config=config)
    finally:
        if routing_soc_present:
            routing["simulated_soc_percent"] = routing_soc_saved
        else:
            routing.pop("simulated_soc_percent", None)
        for key, (present, value) in saved.items():
            if present:
                active[key] = value
            else:
                active.pop(key, None)

    if corrected <= 0:
        return 0

    diagnostic = state.get("completed_flow_soc_continuity")
    if not isinstance(diagnostic, dict):
        return 0
    diagnostic.update(decision_evidence)
    diagnostic["active_elapsed_battery_delta_kwh"] = active_elapsed_delta
    diagnostic["active_elapsed_battery_delta_source"] = active_elapsed_source
    diagnostic["canonical_decision_soc_anchor_mode"] = (
        "settled active-slot boundary proven by rollover continuity"
    )
    diagnostic["canonical_decision_routing_soc_unchanged"] = True
    diagnostic["canonical_decision_routing_soc_percent"] = round(
        candidate["routing_soc_percent"], 3
    )
    diagnostic["canonical_decision_display_current_soc_percent"] = round(
        candidate["display_current_soc_percent"], 3
    )
    diagnostic["canonical_decision_stored_delta_percent"] = round(
        candidate["stored_delta_percent"], 3
    )
    diagnostic["canonical_decision_rollover_residual_before_anchor_percent"] = round(
        candidate["rollover_residual_before_percent"], 3
    )
    diagnostic["canonical_decision_rollover_residual_candidate_percent"] = round(
        candidate["rollover_residual_candidate_percent"], 3
    )
    diagnostic["reporting_only"] = True
    diagnostic["hardware_writes"] = "blocked"
    return corrected


class RestartSocAnchorAgileSmartExportManager(
    ActiveElapsedSocContinuityAgileSmartExportManager
):
    """Publish restart-safe display SOC without changing canonical routing state."""

    def _publish(self, state: dict[str, Any]) -> None:
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
                decisions, history_source = self._persisted_agile_decision_history()
                if history_source is not None:
                    provider_bound = callable(
                        getattr(self, "_persisted_agile_decision_provider", None)
                    )
                    _reconcile_completed_from_persisted_decisions(
                        state,
                        decisions=decisions,
                        now=now,
                        config=config,
                    )
                    _reconcile_restart_boundary_anchor(
                        state,
                        now=now,
                        config=config,
                    )
                    diagnostic = state.get("completed_flow_soc_continuity")
                    if isinstance(diagnostic, dict):
                        diagnostic["canonical_decision_provider_bound"] = provider_bound
                        diagnostic["canonical_decision_history_source"] = history_source

        IntelligentDispatchObservabilityAgileSmartExportManager._publish(self, state)
