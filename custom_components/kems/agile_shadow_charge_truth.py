"""Canonical cheap-charge routing truth for Agile shadow reporting.

The preserved Alpha7.23 shadow adapter was intentionally export-centric. During
a confirmed cheap-charge command it can retain raw house demand as battery-to-
home while the canonical ControlState correctly routes the house from Grid and
requests zero battery discharge. This reporting-only adapter mirrors the already-
planned canonical cheap-charge command into shadow evidence; it never creates a
control target or writes hardware.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .kems_core import ControlState

_INSTALLED = False
_ORIGINAL_BUILD = None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def reconcile_cheap_charge_target(
    candidate: ControlState | None,
    context: dict[str, Any],
    control: ControlState,
) -> tuple[ControlState | None, dict[str, Any]]:
    """Mirror the canonical cheap-charge command into shadow evidence only."""
    if candidate is None:
        return candidate, context

    charge_kw = _number(getattr(control, "desired_charge_power_kw", None))
    if charge_kw is None or charge_kw <= 0.001:
        return candidate, context

    dispatch_mode = str(context.get("dispatch_mode") or "").lower()
    operating_reason = str(getattr(control, "operating_reason", "") or "").lower()
    if "cheap_charge" not in dispatch_mode and "cheap" not in operating_reason:
        return candidate, context

    charge_kw = round(max(charge_kw, 0.0), 3)
    home_kw = round(
        max(
            _number(getattr(control, "desired_battery_to_home_power_kw", None)) or 0.0,
            0.0,
        ),
        3,
    )
    export_kw = round(
        max(
            _number(getattr(control, "desired_battery_export_power_kw", None)) or 0.0,
            0.0,
        ),
        3,
    )
    discharge_kw = round(
        max(
            _number(getattr(control, "desired_total_discharge_power_kw", None)) or 0.0,
            0.0,
        ),
        3,
    )
    grid_export_allowed = bool(
        getattr(
            control,
            "desired_grid_export_allowed",
            getattr(candidate, "desired_grid_export_allowed", False),
        )
    )
    total_output_kw = _number(getattr(control, "total_kh7_ac_output_kw", None))
    headroom_kw = _number(getattr(control, "kh7_output_headroom_kw", None))

    replacements: dict[str, Any] = {
        "desired_work_mode": control.desired_work_mode,
        "desired_charge_power_kw": charge_kw,
        "desired_battery_to_home_power_kw": home_kw,
        "desired_battery_export_power_kw": export_kw,
        "desired_total_discharge_power_kw": discharge_kw,
    }
    if hasattr(candidate, "desired_grid_export_allowed"):
        replacements["desired_grid_export_allowed"] = grid_export_allowed
    if total_output_kw is not None and hasattr(candidate, "total_kh7_ac_output_kw"):
        replacements["total_kh7_ac_output_kw"] = round(max(total_output_kw, 0.0), 3)
    if headroom_kw is not None and hasattr(candidate, "kh7_output_headroom_kw"):
        replacements["kh7_output_headroom_kw"] = round(max(headroom_kw, 0.0), 3)
    corrected = replace(candidate, **replacements)

    updated = dict(context)
    optimizer_target = updated.get("optimizer_target")
    optimizer_target = (
        dict(optimizer_target) if isinstance(optimizer_target, dict) else {}
    )
    optimizer_target.update(
        {
            "charge_kw": charge_kw,
            "battery_to_home_kw": home_kw,
            "battery_export_kw": export_kw,
            "total_discharge_kw": discharge_kw,
        }
    )
    updated["optimizer_target"] = optimizer_target

    parity = updated.get("parity")
    parity = dict(parity) if isinstance(parity, dict) else {}
    parity["charge_target_matches_canonical_control"] = (
        abs(corrected.desired_charge_power_kw - charge_kw) <= 0.001
    )
    if hasattr(corrected, "desired_battery_to_home_power_kw"):
        parity["house_target_matches_optimizer"] = (
            abs(corrected.desired_battery_to_home_power_kw - home_kw) <= 0.001
        )
    if hasattr(corrected, "desired_battery_export_power_kw"):
        parity["export_target_matches_optimizer"] = (
            abs(corrected.desired_battery_export_power_kw - export_kw) <= 0.001
        )
    if hasattr(corrected, "desired_total_discharge_power_kw"):
        parity["discharge_target_matches_optimizer"] = (
            abs(corrected.desired_total_discharge_power_kw - discharge_kw) <= 0.001
        )
    routing_matches = all(
        (
            abs(_number(getattr(corrected, "desired_battery_to_home_power_kw", 0.0)) or 0.0 - home_kw)
            <= 0.001,
            abs(_number(getattr(corrected, "desired_battery_export_power_kw", 0.0)) or 0.0 - export_kw)
            <= 0.001,
            abs(_number(getattr(corrected, "desired_total_discharge_power_kw", 0.0)) or 0.0 - discharge_kw)
            <= 0.001,
        )
    )
    if hasattr(corrected, "desired_grid_export_allowed"):
        routing_matches = routing_matches and (
            corrected.desired_grid_export_allowed == grid_export_allowed
        )
    parity["cheap_charge_routing_matches_canonical_control"] = routing_matches
    updated["parity"] = parity
    updated["parity_passed"] = all(parity.values())
    updated["cheap_charge_target_reconciled"] = True
    updated["charge_target_source"] = "canonical ControlState"
    updated["cheap_charge_routing_source"] = "canonical ControlState"
    updated["hardware_writes"] = "blocked"
    return corrected, updated


def install_shadow_charge_truth() -> None:
    """Install one reporting-only wrapper around the preserved shadow builder."""
    global _INSTALLED, _ORIGINAL_BUILD
    if _INSTALLED:
        return

    # Keep the pure reconciliation helper independent of Home Assistant's
    # dashboard/ESPHome imports. The preserved adapter is only needed when the
    # runtime installer executes inside Home Assistant.
    from . import agile_alpha723_shadow as shadow

    _ORIGINAL_BUILD = shadow.build_agile_shadow_command

    def _build(control, simulation, config, agile_state):
        candidate, context = _ORIGINAL_BUILD(control, simulation, config, agile_state)
        return reconcile_cheap_charge_target(candidate, context, control)

    shadow.build_agile_shadow_command = _build
    _INSTALLED = True
