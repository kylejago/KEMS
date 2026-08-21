"""Alpha7.52 align tomorrow publication reporting with no-reserve policy.

Alpha7.46/7.47 established that a clean Octopus publication gap must not hold
battery energy back for an unpublished price. Alpha7.41's separate tomorrow
progressive-publication state still reported the older full-slot reservation,
which made diagnostics contradict the active no-reserve policy.

Alpha7.52 applies the same reporting policy to tomorrow when some prices have
published successfully and the remaining slots are simply awaiting publication.
Retrieval errors stay conservative. It also normalises sub-0.01 kWh reporting
residuals to zero so a fully covered plan does not display a misleading 0.001
kWh shortfall or blank coverage percentage.

This changes publication/summary evidence only. Current-day deadline safety,
Power Down/Happy Hour priority and real FoxESS hardware permissions are unchanged.
"""

from __future__ import annotations

import math
from typing import Any

from . import agile_alpha741_partial_publication as alpha741
from . import agile_alpha745_plan_clarity as alpha745

_EPSILON = 1e-6
_REPORTING_TOLERANCE_KWH = 0.01


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_tomorrow_publication_gap(
    self,
    state: dict[str, Any],
    progressive: dict[str, Any],
) -> bool:
    """Prove missing tomorrow prices are publication-pending, not fetch errors."""
    if not progressive.get("provisional"):
        return False
    if int(progressive.get("known_price_count") or 0) <= 0:
        return False
    if int(progressive.get("missing_price_count") or 0) <= 0:
        return False
    if state.get("last_error") not in (None, ""):
        return False

    missing = {
        str(item)
        for item in (progressive.get("missing_price_labels") or [])
        if str(item).strip()
    }
    diagnostics = getattr(self, "_kems_alpha727_price_fetch_diagnostics", None)
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    if diagnostics and diagnostics.get("primary_fetch_status") not in (None, "success"):
        return False

    attempts = [
        item for item in diagnostics.get("attempts", []) if isinstance(item, dict)
    ]
    relevant = [item for item in attempts if str(item.get("label")) in missing]
    return not any(
        str(item.get("outcome") or "") == "retrieval_error" for item in relevant
    )


def _progressive_tomorrow_state_alpha752(
    self,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Publish zero reserve for a clean, partially published tomorrow horizon."""
    result = alpha752_original_progressive_tomorrow_state(self, state)
    if not isinstance(result, dict):
        return result
    if not _clean_tomorrow_publication_gap(self, state, result):
        return result

    result.update(
        {
            "unknown_slot_capacity_reserved_kwh": 0.0,
            "unknown_price_policy": (
                "no capacity reserved for unpublished prices; use known prices and "
                "re-rank when new prices publish"
            ),
            "unknown_price_reservation_policy": "none",
            "replan_when_price_publishes": True,
            "no_reserve_progressive_tomorrow": True,
        }
    )
    return result


def _plan_summary_alpha752(self) -> dict[str, Any]:
    """Normalise reporting-only sub-tolerance residuals to zero coverage gap."""
    result = alpha752_original_plan_summary(self)
    if not isinstance(result, dict):
        return result

    exportable = _number(result.get("exportable_battery_energy_kwh"))
    planned = _number(result.get("known_price_planned_export_kwh"))
    reserve = _number(result.get("unknown_price_capacity_reserved_kwh"))
    required_unknown = _number(result.get("required_from_unknown_slots_kwh"))
    if exportable is None or planned is None:
        return result
    if (reserve or 0.0) > _EPSILON or (required_unknown or 0.0) > _EPSILON:
        return result

    residual = max(exportable - planned, 0.0)
    if residual > _REPORTING_TOLERANCE_KWH:
        return result

    result.update(
        {
            "unaccounted_export_requirement_kwh": 0.0,
            "known_price_plan_coverage_percent": 100.0,
            "target_covered": True,
            "reporting_residual_normalised": True,
            "reporting_residual_tolerance_kwh": _REPORTING_TOLERANCE_KWH,
            "raw_reporting_residual_kwh": round(residual, 6),
        }
    )
    return result


def install_alpha752_tomorrow_no_reserve_rounding_patch() -> None:
    """Install tomorrow no-reserve and residual-normalisation reporting fixes."""
    global alpha752_original_plan_summary
    global alpha752_original_progressive_tomorrow_state

    progressive = alpha741._progressive_tomorrow_state
    if not getattr(progressive, "_kems_alpha752_tomorrow_no_reserve", False):
        alpha752_original_progressive_tomorrow_state = progressive
        _progressive_tomorrow_state_alpha752._kems_alpha752_tomorrow_no_reserve = True
        alpha741._progressive_tomorrow_state = _progressive_tomorrow_state_alpha752

    plan_summary = alpha745._plan_summary
    if getattr(plan_summary, "_kems_alpha752_rounding", False):
        return
    alpha752_original_plan_summary = plan_summary
    _plan_summary_alpha752._kems_alpha752_rounding = True
    alpha745._plan_summary = _plan_summary_alpha752
