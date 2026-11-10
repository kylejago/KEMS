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


def _policy_house_override(slot: dict[str, Any]) -> dict[str, float] | None:
    """Preserve a canonical house-only forecast beyond the 15% export target.

    The original future projection uses the independent 10% house floor. The
    legacy total-discharge ledger still budgets to 15% and must not replace a
    proven future home service flow with its smaller house allocation. This is
    a display-only correction; live commands, planner fields and physical paid
    export proof are never changed.
    """
    if (
        slot.get("planning_target_limits_export_only") is not True
        or slot.get("hard_safety_floor_latched") is True
        or slot.get("hard_reserve_floor_active") is True
        or slot.get("flow_scope") != "full slot"
        or slot.get("flow_basis") != "KEMS forecast + final rolling allocation"
    ):
        return None

    action = " ".join(
        str(value)
        for value in (
            slot.get("rolling_action"),
            *(slot.get("actions") if isinstance(slot.get("actions"), list) else ()),
        )
    ).lower()
    if any(
        priority in action for priority in ("cheap charge", "happy hour", "power down")
    ):
        return None

    target = _number(slot.get("planning_target_soc_percent"))
    floor = _number(slot.get("house_import_floor_soc_percent"))
    estimated_soc = _number(slot.get("flow_estimated_soc_percent"))
    planned_home = _number(slot.get("planned_battery_to_home_kwh"))
    planned_export = _number(slot.get("rolling_planned_battery_export_kwh"))
    planned_total = _number(slot.get("planned_total_battery_discharge_kwh"))
    projected_home = _number(slot.get("flow_battery_to_home_kwh"))
    projected_export = _number(slot.get("flow_battery_export_kwh"))
    grid_import = _number(slot.get("flow_grid_import_kwh"))
    grid_charge = _number(slot.get("flow_grid_to_battery_kwh"))
    if any(
        value is None
        for value in (
            target,
            floor,
            estimated_soc,
            planned_home,
            planned_export,
            planned_total,
            projected_home,
            projected_export,
            grid_import,
            grid_charge,
        )
    ):
        return None
    if (
        target <= floor + _EPSILON
        or estimated_soc < floor - 0.1
        or projected_home <= planned_home + _FLOW_TOLERANCE_KWH
        or grid_charge > _FLOW_TOLERANCE_KWH
        or min(planned_home, planned_export, projected_home, projected_export) < 0.0
        or abs(planned_total - planned_home - planned_export) > 0.01
    ):
        return None

    return {
        "canonical_home_kwh": projected_home,
        "planned_home_kwh": planned_home,
        "additional_house_only_kwh": projected_home - planned_home,
        "canonical_export_kwh": projected_export,
        "planned_export_kwh": planned_export,
    }


def _reconcile_future_policy_safe_total_discharge_flow(state: dict[str, Any]) -> int:
    """Preserve the independent 15% export and 10% house-only presentation.

    The legacy parity step must not silently overwrite a verified canonical
    house forecast below 15%, or undo a canonical export cap. These temporary
    planner views are restored in finally; optimiser and physical control are
    untouched.
    """
    protected: list[
        tuple[
            dict[str, Any],
            tuple[Any, Any, Any],
            dict[str, float] | None,
            dict[str, float] | None,
        ]
    ] = []
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
            export_override = _policy_export_override(slot)
            house_override = _policy_house_override(slot)
            if export_override is None and house_override is None:
                continue

            saved = (
                slot["planned_total_battery_discharge_kwh"],
                slot["planned_battery_to_home_kwh"],
                slot["rolling_planned_battery_export_kwh"],
            )
            planned_home = _number(saved[1]) or 0.0
            planned_export = _number(saved[2]) or 0.0
            canonical_export = _number(slot.get("flow_battery_export_kwh"))
            if canonical_export is None:
                canonical_export = planned_export

            effective_home = (
                house_override["canonical_home_kwh"]
                if house_override is not None
                else planned_home
            )
            # Never promote a planner export above either canonical flow or
            # the existing rolling allocation while preserving more home flow.
            effective_export = min(planned_export, max(canonical_export, 0.0))
            slot["planned_battery_to_home_kwh"] = effective_home
            slot["rolling_planned_battery_export_kwh"] = effective_export
            slot["planned_total_battery_discharge_kwh"] = (
                effective_home + effective_export
            )
            protected.append((slot, saved, export_override, house_override))

    try:
        corrected = _reconcile_future_total_discharge_flow(state)
    finally:
        for slot, saved, _export_override, _house_override in protected:
            slot["planned_total_battery_discharge_kwh"] = saved[0]
            slot["planned_battery_to_home_kwh"] = saved[1]
            slot["rolling_planned_battery_export_kwh"] = saved[2]

    export_rows = 0
    house_rows = 0
    for slot, _saved, export_override, house_override in protected:
        if export_override is not None:
            export_rows += 1
            slot["flow_policy_export_cap_applied"] = True
            slot["flow_policy_export_cap_source"] = (
                "canonical future-flow 15% planning-target projection"
            )
            slot["flow_policy_export_cap_kwh"] = round(
                export_override["canonical_export_kwh"], 6
            )
            slot["flow_policy_rolling_export_kwh"] = round(
                export_override["rolling_export_kwh"], 6
            )
            slot["flow_policy_suppressed_export_kwh"] = round(
                export_override["suppressed_export_kwh"], 6
            )
        if house_override is not None:
            house_rows += 1
            slot["flow_policy_house_bridge_preserved"] = True
            slot["flow_policy_house_bridge_source"] = (
                "canonical 10% household floor after 15% export stop"
            )
            slot["flow_policy_house_bridge_canonical_kwh"] = round(
                house_override["canonical_home_kwh"], 6
            )
            slot["flow_policy_house_bridge_legacy_kwh"] = round(
                house_override["planned_home_kwh"], 6
            )
            slot["flow_policy_house_bridge_additional_kwh"] = round(
                house_override["additional_house_only_kwh"], 6
            )
        slot["flow_policy_planner_fields_unchanged"] = True
        if slot.get("flow_total_discharge_parity_applied") is True:
            slot["flow_total_discharge_parity_source"] = (
                "canonical 10% house-only projection + 15% export cap"
                if house_override is not None
                else "rolling house allocation + canonical planning-target export cap"
            )

    diagnostic = state.get("flow_total_discharge_parity")
    if isinstance(diagnostic, dict) and protected:
        diagnostic["policy_export_cap_rows"] = export_rows
        diagnostic["policy_export_cap_preserved"] = export_rows > 0
        diagnostic["policy_house_bridge_rows"] = house_rows
        diagnostic["policy_house_bridge_preserved"] = house_rows > 0
        diagnostic["policy_export_cap_basis"] = (
            "canonical policy-capped export wins over a higher rolling ledger export"
        )
        diagnostic["policy_house_bridge_basis"] = (
            "canonical 10% house-only forecast wins over a smaller 15%-target "
            "rolling house allocation; planner and hardware remain unchanged"
        )
        diagnostic["planner_fields_unchanged"] = True

    return corrected
