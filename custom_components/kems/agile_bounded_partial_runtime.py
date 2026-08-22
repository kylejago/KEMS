"""Alpha 7.28 bounded partial-horizon Agile dispatch.

Alpha7.27 proved that an incomplete Agile horizon can be caused by Octopus
successfully answering a request while omitting the target settlement period.
Alpha7.28 permits only the known-price part of Alpha7.26's reserved provisional
plan to enter the shadow command chain in that narrowly verified case.

Every relevant missing slot must be classified by Alpha7.27 as an upstream
Octopus gap, the current slot must have a real price, and the full maximum
discharge capacity of unresolved relevant slots must remain reserved. Retrieval
failures, ambiguous evidence, unknown current prices, or insufficient reserve
retain the original full horizon hold.

The existing house-first dispatch calculation, 7 kW limits, 10% reserve,
13-point independent validator and strict 0.01 kW candidate-applied replay
remain authoritative. Real FoxESS hardware writes remain blocked.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from . import agile_alpha717_dispatch as alpha717
from . import agile_alpha723_shadow as alpha723
from . import agile_alpha725_nonzero as alpha725
from . import agile_alpha726_provisional as alpha726
from . import agile_rolling_replan as rolling
from . import agile_smart_export_runtime_base as runtime
from .kems_core import ControlConfig, ControlState, SimulationConfig, SimulationState
from .tariff import TariffSettings

_EPSILON = 1e-6
_RESERVE_TOLERANCE_KWH = 0.01
_UPSTREAM_MISSING_OUTCOME = "octopus_missing_price"
_ALLOWED_MISSING_ATTEMPT_OUTCOMES = frozenset(
    {"octopus_slot_not_published", "octopus_no_results"}
)
_PARTIAL_SENSOR = "sensor.kems_agile_partial_horizon_dispatch"
_HORIZON_SENSOR = "sensor.kems_agile_price_horizon_status"
_STATUS_SENSOR = "sensor.kems_agile_smart_export_status"


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_utc(value: Any) -> datetime | None:
    """Parse one ISO timestamp and normalise it to UTC."""
    if value in (None, ""):
        return None
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _recovery_evidence(self, horizon: dict[str, Any]) -> dict[str, Any]:
    """Verify that every relevant missing price is an observed upstream gap."""
    diagnostics = getattr(self, "_kems_alpha727_price_fetch_diagnostics", None)
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    missing_labels = {
        str(item) for item in (horizon.get("missing_labels") or []) if str(item).strip()
    }
    unresolved = {
        str(item)
        for item in (diagnostics.get("unresolved_missing_labels") or [])
        if str(item).strip()
    }
    attempts = [
        item for item in diagnostics.get("attempts", []) if isinstance(item, dict)
    ]
    relevant_attempts = {
        str(item.get("label")): str(item.get("outcome") or "")
        for item in attempts
        if str(item.get("label")) in missing_labels
    }

    primary_ok = diagnostics.get("primary_fetch_status") == "success"
    classified_upstream = (
        diagnostics.get("recovery_outcome") == _UPSTREAM_MISSING_OUTCOME
    )
    labels_match = bool(missing_labels and missing_labels.issubset(unresolved))
    every_missing_attempted = bool(
        missing_labels and missing_labels.issubset(relevant_attempts)
    )
    attempts_are_upstream_gaps = bool(
        every_missing_attempted
        and all(
            relevant_attempts[label] in _ALLOWED_MISSING_ATTEMPT_OUTCOMES
            for label in missing_labels
        )
    )
    verified = bool(
        primary_ok
        and classified_upstream
        and labels_match
        and attempts_are_upstream_gaps
    )

    if not diagnostics:
        reason = "Alpha7.27 price-recovery evidence is unavailable"
    elif not primary_ok:
        reason = "primary Agile price retrieval was not successful"
    elif not classified_upstream:
        reason = "missing price was not classified as an upstream Octopus gap"
    elif not labels_match:
        reason = "current horizon gap does not match unresolved recovery evidence"
    elif not every_missing_attempted:
        reason = "not every relevant missing slot has targeted recovery evidence"
    elif not attempts_are_upstream_gaps:
        reason = "one or more relevant retries were retrieval failures or ambiguous"
    else:
        reason = "Octopus successfully responded but omitted every relevant target slot"

    return {
        "verified": verified,
        "reason": reason,
        "diagnostic_version": diagnostics.get("version"),
        "diagnostic_generated_at": diagnostics.get("generated_at"),
        "recovery_outcome": diagnostics.get("recovery_outcome"),
        "missing_labels": sorted(missing_labels),
        "unresolved_labels": sorted(unresolved),
        "relevant_attempt_outcomes": relevant_attempts,
    }


def _reserve_evidence(
    plan: dict[str, Any],
    horizon: dict[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    """Prove that unresolved relevant slots retain their full power capacity."""
    missing_slots = [
        dict(item)
        for item in horizon.get("missing_slots", [])
        if isinstance(item, dict)
    ]
    deadline = _parse_utc(horizon.get("deadline"))
    max_kw = max(_number(plan.get("effective_discharge_kw")) or 0.0, 0.0)
    required = alpha726._future_missing_capacity_kwh(
        missing_slots,
        now=now,
        deadline=deadline,
        max_kw=max_kw,
    )
    reserved = max(
        _number(plan.get("provisional_reserved_unknown_capacity_kwh")) or 0.0,
        0.0,
    )
    sufficient = bool(
        required <= _EPSILON or reserved + _RESERVE_TOLERANCE_KWH >= required
    )
    return {
        "required_kwh": round(required, 3),
        "reserved_kwh": round(reserved, 3),
        "sufficient": sufficient,
        "effective_discharge_kw": round(max_kw, 3),
    }


def _current_price_evidence(
    state: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Return evidence that the active slot has a real known Agile price."""
    slot = alpha717._current_slot(state, now)
    if not isinstance(slot, dict):
        return {
            "known": False,
            "label": None,
            "valid_from": None,
            "rate_pence": None,
        }
    rate = _number(slot.get("rate_pence"))
    return {
        "known": rate is not None,
        "label": slot.get("label"),
        "valid_from": slot.get("valid_from"),
        "rate_pence": rate,
    }


def _selected_by_start(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return Alpha7.26's reserved known-price allocation by slot start."""
    return {
        str(item.get("valid_from") or ""): dict(item)
        for item in plan.get("provisional_selected_slots", [])
        if isinstance(item, dict)
        and (_number(item.get("planned_battery_export_kwh")) or 0.0) > _EPSILON
    }


def _restore_known_allocations(
    state: dict[str, Any],
    selected: dict[str, dict[str, Any]],
    *,
    now: datetime,
) -> None:
    """Restore only reserved known-price allocations after Alpha7.22's hold."""
    now_utc = now.astimezone(UTC)
    for slot in state.get("today_slots", []):
        if not isinstance(slot, dict):
            continue
        start = _parse_utc(slot.get("valid_from"))
        end = _parse_utc(slot.get("valid_to"))
        if start is None or end is None or end <= now_utc:
            continue
        selected_slot = selected.get(str(slot.get("valid_from") or "")) or {}
        planned = max(
            _number(selected_slot.get("planned_battery_export_kwh")) or 0.0,
            0.0,
        )
        slot["rolling_planned_battery_export_kwh"] = round(planned, 3)
        if planned > _EPSILON:
            action = "known-price export eligible — bounded partial horizon"
        else:
            action = "hold — bounded partial horizon replan"
        slot["rolling_action"] = action
        if not (start <= now_utc < end):
            slot["actions"] = [action]


def _executable_selected_slots(
    plan: dict[str, Any],
    state: dict[str, Any],
    *,
    now: datetime,
    export_target_kw: float,
) -> list[dict[str, Any]]:
    """Apply current house-load headroom to the known-price allocation."""
    selected = [
        dict(item)
        for item in plan.get("provisional_selected_slots", [])
        if isinstance(item, dict)
    ]
    current = alpha717._current_slot(state, now)
    current_start = (
        str(current.get("valid_from") or "") if isinstance(current, dict) else ""
    )
    remaining_hours = alpha717._remaining_current_slot_hours(state, now)
    current_energy = round(max(export_target_kw, 0.0) * remaining_hours, 3)

    rebuilt: list[dict[str, Any]] = []
    for item in selected:
        if str(item.get("valid_from") or "") == current_start:
            item["planned_battery_export_kwh"] = current_energy
            item["bounded_current_load_adjusted"] = True
        if (_number(item.get("planned_battery_export_kwh")) or 0.0) > _EPSILON:
            rebuilt.append(item)
    rebuilt.sort(key=lambda item: str(item.get("valid_from") or ""))
    return rebuilt


def _next_selected_slot(
    selected: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any] | None:
    """Return the next executable known-price slot."""
    now_utc = now.astimezone(UTC)
    for item in selected:
        start = _parse_utc(item.get("valid_from"))
        if start is not None and start >= now_utc:
            return item
    return selected[0] if selected else None


def _apply_bounded_partial_dispatch(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> None:
    """Replace only a verified upstream-gap full hold with bounded dispatch."""
    horizon = state.get("planning_horizon")
    horizon = horizon if isinstance(horizon, dict) else {}
    was_held = bool(plan.get("price_horizon_battery_export_held"))
    provisional_active = bool(plan.get("provisional_plan_active"))
    current_known = bool(horizon.get("current_slot_known"))
    recovery = _recovery_evidence(self, horizon)
    reserve = _reserve_evidence(plan, horizon, now=now)
    current_price = _current_price_evidence(state, now)

    eligible = bool(
        was_held
        and provisional_active
        and current_known
        and current_price.get("known")
        and recovery.get("verified")
        and reserve.get("sufficient")
    )
    if not was_held:
        reason = "normal horizon path already permits dispatch"
    elif not provisional_active:
        reason = "no Alpha7.26 provisional known-price plan is available"
    elif not current_known or not current_price.get("known"):
        reason = "current Agile settlement price is unknown"
    elif not recovery.get("verified"):
        reason = str(recovery.get("reason") or "upstream gap is not verified")
    elif not reserve.get("sufficient"):
        reason = "full unresolved-slot discharge capacity has not been reserved"
    else:
        reason = (
            "verified upstream price gap with current price known and unknown-slot "
            "capacity fully reserved"
        )

    plan.update(
        {
            "bounded_partial_horizon_eligible": eligible,
            "bounded_partial_horizon_reason": reason,
            "bounded_upstream_gap_verified": bool(recovery.get("verified")),
            "bounded_recovery_evidence": recovery,
            "bounded_current_price_known": bool(current_price.get("known")),
            "bounded_current_price": current_price,
            "bounded_unknown_capacity_required_kwh": reserve.get("required_kwh"),
            "bounded_unknown_capacity_reserved_kwh": reserve.get("reserved_kwh"),
            "bounded_unknown_capacity_sufficient": bool(reserve.get("sufficient")),
            "bounded_unknown_slot_dispatch_blocked": True,
            "bounded_partial_horizon_dispatch_active": False,
        }
    )
    if not eligible:
        return

    selected_map = _selected_by_start(plan)
    _restore_known_allocations(state, selected_map, now=now)
    targets = alpha717._dispatch_targets(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )
    export_target = max(_number(targets.get("battery_export_target_kw")) or 0.0, 0.0)
    discharge_target = max(
        _number(targets.get("battery_discharge_target_kw")) or 0.0,
        0.0,
    )
    house_target = max(_number(targets.get("house_battery_kw")) or 0.0, 0.0)
    selected = _executable_selected_slots(
        plan,
        state,
        now=now,
        export_target_kw=export_target,
    )
    planned = round(
        sum(
            max(_number(item.get("planned_battery_export_kwh")) or 0.0, 0.0)
            for item in selected
        ),
        3,
    )
    reserved = max(
        _number(plan.get("bounded_unknown_capacity_reserved_kwh")) or 0.0,
        0.0,
    )
    exportable = max(
        _number(plan.get("exportable_battery_energy_kwh")) or 0.0,
        0.0,
    )

    if export_target > alpha725.NONZERO_EXPORT_THRESHOLD_KW:
        action = (
            "bounded partial-horizon export — known price; unknown-slot capacity "
            "reserved"
        )
    else:
        action = (
            "bounded partial-horizon hold — current known slot not selected; "
            "unknown-slot capacity reserved"
        )

    plan.update(
        {
            "bounded_partial_horizon_dispatch_active": True,
            "economic_plan_status": "bounded_partial_horizon",
            "dispatch_blocked_for_price_horizon": False,
            "dispatch_permitted_battery_export_kw": round(export_target, 3),
            "dispatch_mode": "bounded_partial_horizon",
            "bounded_underlying_dispatch_mode": targets.get("mode"),
            "dispatch_action": action,
            "current_house_battery_kw": round(house_target, 3),
            "current_battery_discharge_target_kw": round(discharge_target, 3),
            "current_battery_export_target_kw": round(export_target, 3),
            "planned_battery_export_kwh": planned,
            "selected_slots": selected,
            "next_export_slot": _next_selected_slot(selected, now),
            "unallocated_exportable_kwh": round(
                max(exportable - planned - reserved, 0.0),
                3,
            ),
            "price_horizon_battery_export_held": False,
            "price_horizon_status": "bounded_partial_horizon",
        }
    )
    horizon.update(
        {
            "battery_export_held": False,
            "status": "bounded_partial_horizon",
            "bounded_partial_dispatch": True,
            "upstream_gap_verified": True,
            "unknown_capacity_required_kwh": reserve.get("required_kwh"),
            "unknown_capacity_reserved_kwh": reserve.get("reserved_kwh"),
            "unknown_capacity_sufficient": True,
            "unknown_slot_dispatch_blocked": True,
        }
    )
    state["planning_horizon"] = horizon
    state["current_action"] = action

    current_slot = alpha717._current_slot(state, now)
    if isinstance(current_slot, dict):
        remaining_hours = alpha717._remaining_current_slot_hours(state, now)
        current_slot["rolling_target_battery_export_kw"] = round(export_target, 3)
        current_slot["rolling_target_total_discharge_kw"] = round(discharge_target, 3)
        current_slot["rolling_planned_battery_export_kwh"] = round(
            export_target * remaining_hours,
            3,
        )
        current_slot["rolling_action"] = action
        current_slot["dispatch_action"] = action


def _rolling_plan_with_alpha728(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Apply bounded permission after Alpha7.26/7.27 have produced evidence."""
    plan = alpha728_original_rolling_plan(
        self,
        state,
        now=now,
        config=config,
        tariff=tariff,
    )
    if isinstance(plan, dict) and plan.get("available"):
        _apply_bounded_partial_dispatch(
            self,
            state,
            plan,
            now=now,
            config=config,
            tariff=tariff,
        )
    return plan


def _evaluate_with_bounded_nonzero_proof(
    control: ControlState,
    simulation: SimulationState,
    config: ControlConfig,
    agile_state: dict[str, Any],
) -> dict[str, Any]:
    """Allow Alpha7.25's strict proof on a verified bounded-partial horizon."""
    result = alpha728_original_evaluate(control, simulation, config, agile_state)
    plan = agile_state.get("rolling_export_plan")
    plan = plan if isinstance(plan, dict) else {}
    bounded = bool(plan.get("bounded_partial_horizon_dispatch_active"))
    if not bounded:
        return result

    result["bounded_partial_horizon"] = {
        "active": True,
        "reason": plan.get("bounded_partial_horizon_reason"),
        "upstream_gap_verified": bool(plan.get("bounded_upstream_gap_verified")),
        "current_price_known": bool(plan.get("bounded_current_price_known")),
        "unknown_capacity_required_kwh": plan.get(
            "bounded_unknown_capacity_required_kwh"
        ),
        "unknown_capacity_reserved_kwh": plan.get(
            "bounded_unknown_capacity_reserved_kwh"
        ),
        "unknown_capacity_sufficient": bool(
            plan.get("bounded_unknown_capacity_sufficient")
        ),
        "unknown_slot_dispatch_blocked": bool(
            plan.get("bounded_unknown_slot_dispatch_blocked")
        ),
    }

    candidate = result.get("candidate")
    if not isinstance(candidate, dict):
        return result
    candidate_export = max(_number(candidate.get("battery_export_kw")) or 0.0, 0.0)
    optimizer = result.get("optimizer_target") or {}
    optimizer_export = max(_number(optimizer.get("battery_export_kw")) or 0.0, 0.0)
    if candidate_export <= alpha725.NONZERO_EXPORT_THRESHOLD_KW:
        proof = result.get("nonzero_export_proof")
        if isinstance(proof, dict):
            proof["dispatch_basis"] = "bounded_partial_horizon"
            proof["price_horizon_safe_for_dispatch"] = True
        return result

    replay = alpha725._candidate_applied_replay(result, config)
    tracking = (replay or {}).get("tracking") or {}
    within = tracking.get("within_tolerance") or {}
    safety = result.get("safety") or {}
    target_soc = _number(candidate.get("minimum_soc_percent"))
    candidate_total = max(
        _number(candidate.get("total_discharge_kw")) or 0.0,
        0.0,
    )
    candidate_ac = max(
        _number(candidate.get("total_kh7_ac_output_kw")) or 0.0,
        0.0,
    )

    checks = {
        "nonzero_optimizer_export": (
            optimizer_export > alpha725.NONZERO_EXPORT_THRESHOLD_KW
        ),
        "export_target_matches_optimizer": (
            abs(candidate_export - optimizer_export) <= 0.001
        ),
        "command_parity": bool(result.get("parity_passed")),
        "bounded_partial_horizon_active": bounded,
        "verified_octopus_missing_price": bool(
            plan.get("bounded_upstream_gap_verified")
        ),
        "current_price_known": bool(plan.get("bounded_current_price_known")),
        "unknown_capacity_fully_reserved": bool(
            plan.get("bounded_unknown_capacity_sufficient")
        ),
        "unknown_slot_dispatch_blocked": bool(
            plan.get("bounded_unknown_slot_dispatch_blocked")
        ),
        "price_horizon_not_held": not bool(result.get("battery_export_held")),
        "feed_in_first_mode": candidate.get("desired_work_mode") == "Feed-in First",
        "grid_export_allowed": bool(candidate.get("grid_export_allowed")),
        "independent_safety_13_of_13": bool(
            safety.get("passed")
            and safety.get("passed_checks") == 13
            and safety.get("total_checks") == 13
        ),
        "strict_outcome_parity": bool(
            within and all(bool(value) for value in within.values())
        ),
        "strict_tracking_100_percent": (
            tracking.get("tracking_score_percent") == 100.0
        ),
        "discharge_within_limit": (candidate_total <= config.max_discharge_kw + 1e-9),
        "kh7_ac_within_limit": candidate_ac <= config.inverter_limit_kw + 1e-9,
        "minimum_soc_respected": bool(
            target_soc is not None
            and target_soc + 1e-9 >= config.normal_reserve_percent
        ),
        "hardware_writes_blocked": bool(
            not result.get("safe_to_write_hardware")
            and not candidate.get("commands_permitted")
        ),
    }
    passed = bool(replay and all(checks.values()))
    proof = {
        "state": (
            "PASS — non-zero Agile export proof"
            if passed
            else "CHECK — non-zero Agile export proof"
        ),
        "qualified": True,
        "passed": passed,
        "dispatch_basis": "bounded_partial_horizon",
        "strict_tolerance_kw": alpha725.STRICT_TRACKING_TOLERANCE_KW,
        "candidate_export_kw": round(candidate_export, 3),
        "optimizer_export_kw": round(optimizer_export, 3),
        "price_horizon_complete": result.get("price_horizon_complete") is True,
        "price_horizon_safe_for_dispatch": True,
        "battery_export_held": bool(result.get("battery_export_held")),
        "unknown_capacity_required_kwh": plan.get(
            "bounded_unknown_capacity_required_kwh"
        ),
        "unknown_capacity_reserved_kwh": plan.get(
            "bounded_unknown_capacity_reserved_kwh"
        ),
        "checks": checks,
        "replay": replay,
        "hardware_writes": "blocked",
    }

    result["baseline_tracking"] = result.get("tracking")
    result["baseline_outcome_parity"] = result.get("outcome_parity")
    result["tracking"] = tracking
    result["outcome_parity"] = {
        "passed": passed,
        "basis": tracking.get("basis"),
        "tracking_score_percent": tracking.get("tracking_score_percent"),
        "within_tolerance": tracking.get("within_tolerance"),
    }
    result["outcome_parity_passed"] = passed
    result["nonzero_export_proof"] = proof
    result["status"] = proof["state"]
    result["safe_to_write_hardware"] = False
    return result


def _publish_with_alpha728(self, state: dict[str, Any]) -> None:
    """Publish bounded permission without exposing a hardware write path."""
    alpha728_original_publish(self, state)
    plan = state.get("rolling_export_plan")
    plan = plan if isinstance(plan, dict) else {}
    horizon = state.get("planning_horizon")
    horizon = horizon if isinstance(horizon, dict) else {}
    active = bool(plan.get("bounded_partial_horizon_dispatch_active"))
    eligible = bool(plan.get("bounded_partial_horizon_eligible"))

    if active:
        sensor_state = "ACTIVE — bounded known-price dispatch"
    elif eligible:
        sensor_state = "READY — bounded partial horizon"
    elif horizon.get("complete"):
        sensor_state = "Inactive — complete price horizon"
    elif horizon:
        sensor_state = "BLOCKED — incomplete price horizon"
    else:
        sensor_state = "Unavailable"

    attrs = {
        "friendly_name": "Agile bounded partial-horizon dispatch",
        "mode": "simulation_shadow_only",
        "active": active,
        "eligible": eligible,
        "reason": plan.get("bounded_partial_horizon_reason"),
        "dispatch_mode": plan.get("dispatch_mode"),
        "dispatch_action": plan.get("dispatch_action"),
        "dispatch_permitted_battery_export_kw": plan.get(
            "dispatch_permitted_battery_export_kw"
        ),
        "current_price_known": plan.get("bounded_current_price_known"),
        "upstream_gap_verified": plan.get("bounded_upstream_gap_verified"),
        "missing_labels": horizon.get("missing_labels"),
        "unknown_capacity_required_kwh": plan.get(
            "bounded_unknown_capacity_required_kwh"
        ),
        "unknown_capacity_reserved_kwh": plan.get(
            "bounded_unknown_capacity_reserved_kwh"
        ),
        "unknown_capacity_sufficient": plan.get("bounded_unknown_capacity_sufficient"),
        "unknown_slot_dispatch_blocked": True,
        "price_fetch_status": state.get("price_fetch_status"),
        "hardware_writes": "blocked",
        "real_backend_available": False,
    }
    self._set(_PARTIAL_SENSOR, sensor_state, attrs)

    if active:
        self._set(
            _HORIZON_SENSOR,
            "Bounded partial",
            {
                "friendly_name": "Agile battery-export price horizon",
                "mode": "simulation_only",
                **horizon,
                "hardware_writes": "blocked",
            },
        )
        existing = self._hass.states.get(_STATUS_SENSOR)
        status_attrs = dict(existing.attributes) if existing is not None else {}
        status_attrs.update(attrs)
        self._set(_STATUS_SENSOR, "Ready — bounded partial horizon", status_attrs)


def install_alpha728_bounded_partial_horizon_patch() -> None:
    """Install bounded known-price dispatch after Alpha7.27 recovery evidence."""
    global alpha728_original_evaluate
    global alpha728_original_publish
    global alpha728_original_rolling_plan

    current_rolling = rolling._rolling_plan
    if not getattr(current_rolling, "_kems_alpha728_bounded_partial", False):
        alpha728_original_rolling_plan = current_rolling
        _rolling_plan_with_alpha728._kems_alpha728_bounded_partial = True
        rolling._rolling_plan = _rolling_plan_with_alpha728

    current_evaluate = alpha723.evaluate_agile_shadow_command
    if not getattr(current_evaluate, "_kems_alpha728_bounded_partial", False):
        alpha728_original_evaluate = current_evaluate
        _evaluate_with_bounded_nonzero_proof._kems_alpha728_bounded_partial = True
        alpha723.evaluate_agile_shadow_command = _evaluate_with_bounded_nonzero_proof

    current_publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(current_publish, "_kems_alpha728_bounded_partial", False):
        alpha728_original_publish = current_publish
        _publish_with_alpha728._kems_alpha728_bounded_partial = True
        runtime.EfficientAgileSmartExportManager._publish = _publish_with_alpha728
