"""Policy-aware publication guard for Agile future total-discharge parity.

The historical total-discharge parity owner is still responsible for restoring
missing future house/export presentation flow from the rolling ledger. Alpha9.24
adds the final planning-policy boundary around that owner so a legacy rolling
allocation cannot raise deliberate export above an already-capped canonical
future-flow projection.

This module is reporting-only. It never changes optimiser allocations, dispatch,
safety state, tariff decisions, or hardware-write authority.
"""

from __future__ import annotations

import math
from typing import Any

from .agile_flow_total_discharge_parity import (
    _dt,
    _reconcile_future_total_discharge_flow,
)

_EPSILON = 1e-6
_FLOW_TOLERANCE_KWH = 0.0005


def _number(value: Any) -> float | None:
    """Return one finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _policy_export_override(slot: dict[str, Any]) -> dict[str, float] | None:
    """Return a proven canonical export cap for one policy-marked future row."""
    if slot.get("planning_target_limits_export_only") is not True:
        return None

    planning_target = _number(slot.get("planning_target_soc_percent"))
    house_floor = _number(slot.get("house_import_floor_soc_percent"))
    canonical_export = _number(slot.get("flow_battery_export_kwh"))
    planned_export = _number(slot.get("rolling_planned_battery_export_kwh"))
    planned_home = _number(slot.get("planned_battery_to_home_kwh"))
    planned_total = _number(slot.get("planned_total_battery_discharge_kwh"))
    if (
        planning_target is None
        or house_floor is None
        or canonical_export is None
        or planned_export is None
        or planned_home is None
        or planned_total is None
    ):
        return None
    if planning_target <= house_floor + _EPSILON:
        return None
    if abs(planned_total - (planned_home + planned_export)) > 0.01:
        return None

    canonical_export = max(canonical_export, 0.0)
    planned_export = max(planned_export, 0.0)
    planned_home = max(planned_home, 0.0)
    if planned_export <= canonical_export + _FLOW_TOLERANCE_KWH:
        return None

    return {
        "canonical_export_kwh": canonical_export,
        "rolling_export_kwh": planned_export,
        "planned_home_kwh": planned_home,
        "suppressed_export_kwh": planned_export - canonical_export,
    }


def _reconcile_future_policy_safe_total_discharge_flow(state: dict[str, Any]) -> int:
    """Run future parity without letting the legacy ledger undo an export cap.

    The established parity owner may still restore its planned house allocation.
    For strict-future rows that explicitly prove the Alpha9 planning target limits
    deliberate export only, its temporary ledger view is capped to the canonical
    projected export. Original planner fields are restored in ``finally`` so
    optimiser and dispatch evidence remain owned by their existing producers.
    """
    protected: list[tuple[dict[str, Any], tuple[float, float], dict[str, float]]] = []
    routing = state.get("current_routing_snapshot")
    future_boundary = (
        _dt(routing.get("routing_valid_to")) if isinstance(routing, dict) else None
    )
    slots = state.get("today_slots")
    if future_boundary is not None and isinstance(slots, list):
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            start = _dt(slot.get("valid_from"))
            if start is None or start < future_boundary:
                continue
            override = _policy_export_override(slot)
            if override is None:
                continue

            saved = (
                slot["planned_total_battery_discharge_kwh"],
                slot["rolling_planned_battery_export_kwh"],
            )
            slot["rolling_planned_battery_export_kwh"] = override[
                "canonical_export_kwh"
            ]
            slot["planned_total_battery_discharge_kwh"] = (
                override["planned_home_kwh"] + override["canonical_export_kwh"]
            )
            protected.append((slot, saved, override))

    try:
        corrected = _reconcile_future_total_discharge_flow(state)
    finally:
        for slot, saved, _override in protected:
            slot["planned_total_battery_discharge_kwh"] = saved[0]
            slot["rolling_planned_battery_export_kwh"] = saved[1]

    for slot, _saved, override in protected:
        slot["flow_policy_export_cap_applied"] = True
        slot["flow_policy_export_cap_source"] = (
            "canonical future-flow 15% planning-target projection"
        )
        slot["flow_policy_export_cap_kwh"] = round(override["canonical_export_kwh"], 6)
        slot["flow_policy_rolling_export_kwh"] = round(
            override["rolling_export_kwh"], 6
        )
        slot["flow_policy_suppressed_export_kwh"] = round(
            override["suppressed_export_kwh"], 6
        )
        slot["flow_policy_planner_fields_unchanged"] = True
        if slot.get("flow_total_discharge_parity_applied") is True:
            slot["flow_total_discharge_parity_source"] = (
                "rolling house allocation + canonical planning-target export cap"
            )

    diagnostic = state.get("flow_total_discharge_parity")
    if isinstance(diagnostic, dict) and protected:
        diagnostic["policy_export_cap_rows"] = len(protected)
        diagnostic["policy_export_cap_preserved"] = True
        diagnostic["policy_export_cap_basis"] = (
            "canonical policy-capped export wins over higher rolling ledger export; "
            "rolling house allocation remains eligible for presentation parity"
        )
        diagnostic["planner_fields_unchanged"] = True

    return corrected
