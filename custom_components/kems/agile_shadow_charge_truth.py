"""Canonical cheap-charge truth for Agile shadow reporting.

The preserved Alpha7.23 shadow adapter was intentionally export-centric and set
charge power to zero. During a confirmed cheap-charge command that makes the
settled shadow target disagree with the canonical ControlState even though the
digital twin charges correctly. This adapter mirrors only the already-planned
canonical charge command; it never creates a charge target or writes hardware.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import agile_alpha723_shadow as shadow
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
    corrected = replace(
        candidate,
        desired_work_mode=control.desired_work_mode,
        desired_charge_power_kw=charge_kw,
    )
    updated = dict(context)
    optimizer_target = updated.get("optimizer_target")
    optimizer_target = dict(optimizer_target) if isinstance(optimizer_target, dict) else {}
    optimizer_target["charge_kw"] = charge_kw
    updated["optimizer_target"] = optimizer_target
    parity = updated.get("parity")
    parity = dict(parity) if isinstance(parity, dict) else {}
    parity["charge_target_matches_canonical_control"] = (
        abs(corrected.desired_charge_power_kw - charge_kw) <= 0.001
    )
    updated["parity"] = parity
    updated["parity_passed"] = all(parity.values())
    updated["cheap_charge_target_reconciled"] = True
    updated["charge_target_source"] = "canonical ControlState"
    return corrected, updated


def install_shadow_charge_truth() -> None:
    """Install one reporting-only wrapper around the preserved shadow builder."""
    global _INSTALLED, _ORIGINAL_BUILD
    if _INSTALLED:
        return

    _ORIGINAL_BUILD = shadow.build_agile_shadow_command

    def _build(control, simulation, config, agile_state):
        candidate, context = _ORIGINAL_BUILD(control, simulation, config, agile_state)
        return reconcile_cheap_charge_target(candidate, context, control)

    shadow.build_agile_shadow_command = _build
    _INSTALLED = True
