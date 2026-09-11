"""Final policy-label clarity for KEMS Agile diagnostics.

Older compatibility layers still carry historical 10% wording from when the
optimiser target and physical battery floor were the same concept. The active
policy now separates them: 15% limits deliberate export, ordinary Home service
may continue toward the independent 10% absolute floor, and a latched 10% stop
recovers at 12%.

This module only clarifies already-published human-readable labels immediately
before Home Assistant entity publication. It never changes optimiser fields,
energy allocations, SOC arithmetic, tariffs, command targets, or hardware-write
authority.
"""

from __future__ import annotations

import math
from typing import Any

from .agile_intelligent_dispatch_observability import (
    IntelligentDispatchObservabilityAgileSmartExportManager,
)
from .agile_safety_floor import (
    HARD_SAFETY_FLOOR_SOC_PERCENT,
    HARD_SAFETY_RECOVERY_SOC_PERCENT,
    PLANNING_TARGET_SOC_PERCENT,
)

_EPSILON = 1e-6
_original_publish = None


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _percent_text(value: float) -> str:
    """Format a policy percentage without unnecessary trailing zeroes."""
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


def _house_bridge_action(target_soc: float, floor_soc: float) -> str:
    """Return the canonical customer-facing action after export target is reached."""
    return (
        f"{_percent_text(target_soc)}% deliberate-export target reached — "
        f"house-only battery bridge toward {_percent_text(floor_soc)}% absolute "
        "floor until cheap charge; no deliberate export"
    )


def _clarify_policy_action_labels(state: dict[str, Any]) -> dict[str, Any]:
    """Replace stale historical reserve labels from canonical flow truth only."""
    rolling = state.get("rolling_export_plan")
    rolling = rolling if isinstance(rolling, dict) else {}
    target_soc = (
        _number(rolling.get("planning_target_soc_percent"))
        or _number(rolling.get("target_soc_percent"))
        or PLANNING_TARGET_SOC_PERCENT
    )
    floor_soc = (
        _number(rolling.get("hard_safety_floor_soc_percent"))
        or HARD_SAFETY_FLOOR_SOC_PERCENT
    )
    recovery_soc = (
        _number(rolling.get("hard_safety_recovery_soc_percent"))
        or HARD_SAFETY_RECOVERY_SOC_PERCENT
    )
    hard_latched = bool(rolling.get("hard_safety_floor_active"))
    action = _house_bridge_action(target_soc, floor_soc)
    clarified_fields = 0

    routing = state.get("current_routing_snapshot")
    if isinstance(routing, dict) and not hard_latched:
        routing_action = str(routing.get("routing_action") or "")
        routing_soc = _number(routing.get("simulated_soc_percent"))
        house_kw = max(_number(routing.get("battery_to_home_kw")) or 0.0, 0.0)
        export_kw = max(_number(routing.get("battery_export_kw")) or 0.0, 0.0)
        reached = (
            bool(rolling.get("planning_target_reached"))
            or (routing_soc is not None and routing_soc <= target_soc + _EPSILON)
            or "planning target reached" in routing_action.lower()
        )
        if reached and house_kw > _EPSILON and export_kw <= _EPSILON:
            if routing.get("routing_action") != action:
                routing["routing_action"] = action
                clarified_fields += 1

    for slot in state.get("today_slots", []) or []:
        if not isinstance(slot, dict):
            continue
        if slot.get("planning_target_limits_export_only") is not True:
            continue
        if slot.get("hard_safety_floor_latched") is True:
            continue
        flow_soc = _number(slot.get("flow_estimated_soc_percent"))
        flow_home = max(_number(slot.get("flow_battery_to_home_kwh")) or 0.0, 0.0)
        flow_export = max(_number(slot.get("flow_battery_export_kwh")) or 0.0, 0.0)
        stale_action = "10% reserve floor" in str(slot.get("rolling_action") or "").lower()
        stale_actions = any(
            "10% reserve floor" in str(value).lower()
            for value in (slot.get("actions") or [])
        )
        at_or_below_target = flow_soc is not None and flow_soc <= target_soc + 0.15
        if (
            flow_home > _EPSILON
            and flow_export <= _EPSILON
            and (at_or_below_target or stale_action or stale_actions)
        ):
            if slot.get("rolling_action") != action:
                slot["rolling_action"] = action
                clarified_fields += 1
            if slot.get("actions") != [action]:
                slot["actions"] = [action]
                clarified_fields += 1

    evidence = {
        "active": True,
        "clarified_fields": clarified_fields,
        "planning_target_soc_percent": round(target_soc, 3),
        "house_import_floor_soc_percent": round(floor_soc, 3),
        "hard_safety_recovery_soc_percent": round(recovery_soc, 3),
        "policy": (
            "planning target limits deliberate export only; ordinary Home battery "
            "service may continue toward the independent absolute floor"
        ),
        "reporting_only": True,
        "hardware_writes": "blocked",
    }
    state["policy_action_observability"] = evidence
    return evidence


def install_observability_clarity() -> None:
    """Clarify final labels immediately before existing entity publication."""
    global _original_publish
    publish = IntelligentDispatchObservabilityAgileSmartExportManager._publish
    if getattr(publish, "_kems_observability_clarity", False):
        return
    _original_publish = publish

    def publish_with_observability_clarity(self, state: dict[str, Any]) -> None:
        _clarify_policy_action_labels(state)
        _original_publish(self, state)

    publish_with_observability_clarity._kems_observability_clarity = True
    IntelligentDispatchObservabilityAgileSmartExportManager._publish = (
        publish_with_observability_clarity
    )
