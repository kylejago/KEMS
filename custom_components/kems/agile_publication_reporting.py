"""Canonical Agile publication-gap reporting reconciliation.

This Alpha8 module carries forward the proven Alpha7.50 and Alpha7.52 reporting
behaviour without keeping those version-named patch modules in the executable
runtime chain. It changes reporting/diagnostic evidence only: optimiser dispatch,
deadline safety and hardware-write permissions remain untouched.
"""

from __future__ import annotations

import math
from typing import Any

from . import agile_alpha741_partial_publication as alpha741
from . import agile_alpha745_plan_clarity as alpha745

_EPSILON = 1e-6
_REPORTING_TOLERANCE_KWH = 0.01
_PLAN_SENSOR = "sensor.kems_agile_rolling_export_plan"
_SLOT_SENSOR = "sensor.kems_agile_slot_decisions_today"


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_publication_gap(attrs: dict[str, Any]) -> bool:
    """Return true only for a verified Octopus publication omission."""
    recovery = attrs.get("bounded_recovery_evidence")
    recovery = dict(recovery) if isinstance(recovery, dict) else {}
    return bool(
        recovery.get("verified")
        and recovery.get("recovery_outcome") == "octopus_missing_price"
    )


def _effective_no_reserve(attrs: dict[str, Any]) -> bool:
    """Prove the current executable path is not reserving unknown capacity."""
    provisional = max(
        _number(attrs.get("provisional_reserved_unknown_capacity_kwh")) or 0.0,
        0.0,
    )
    bounded_active = bool(attrs.get("bounded_partial_horizon_dispatch_active"))
    return (
        _clean_publication_gap(attrs) and not bounded_active and provisional <= _EPSILON
    )


def _plan_summary_no_reserve(self) -> dict[str, Any]:
    """Publish the effective no-reserve policy instead of stale bounded evidence."""
    result = _original_no_reserve_plan_summary(self)
    rolling = self._hass.states.get(_PLAN_SENSOR)
    attrs = dict(rolling.attributes) if rolling is not None else {}
    if not _effective_no_reserve(attrs):
        return result

    exportable = max(
        _number(result.get("exportable_battery_energy_kwh")) or 0.0,
        0.0,
    )
    planned = max(
        _number(result.get("known_price_planned_export_kwh")) or 0.0,
        0.0,
    )
    unaccounted = max(exportable - planned, 0.0)
    coverage = 100.0 if exportable <= 0.01 else min(planned / exportable * 100.0, 100.0)
    result.update(
        {
            "unknown_price_capacity_reserved_kwh": 0.0,
            "required_from_unknown_slots_kwh": 0.0,
            "unaccounted_export_requirement_kwh": round(unaccounted, 3),
            "known_price_plan_coverage_percent": round(coverage, 1),
            "target_covered": unaccounted <= 0.01,
            "target_status": (
                "Covered by published-price export plan; unpublished slots will "
                "be re-ranked when their prices arrive"
                if unaccounted <= 0.01
                else (
                    f"Published prices currently leave {unaccounted:.3f} kWh "
                    "unallocated; replan as new prices arrive"
                )
            ),
            "unknown_price_reservation_policy": "none",
            "replan_when_price_publishes": True,
            "no_reserve_reporting_reconciled": True,
        }
    )
    return result


def _annotate_unknown_rows_no_reserve(self, plan: dict[str, Any]) -> None:
    """Replace stale per-slot reserve wording after older annotations run."""
    _original_no_reserve_annotate(self, plan)

    rolling = self._hass.states.get(_PLAN_SENSOR)
    rolling_attrs = dict(rolling.attributes) if rolling is not None else {}
    if not _effective_no_reserve(rolling_attrs):
        return

    slot_state = self._hass.states.get(_SLOT_SENSOR)
    if slot_state is None:
        return
    attrs = dict(slot_state.attributes)
    slots = [dict(item) for item in attrs.get("slots", []) if isinstance(item, dict)]
    changed = False
    for row in slots:
        decision = str(row.get("decision") or "")
        if not decision.startswith("Waiting for Octopus price"):
            continue
        row["reserved_unknown_slot_capacity_kwh"] = 0.0
        row["currently_needed_from_this_unknown_capacity_kwh"] = 0.0
        row["decision"] = (
            "Waiting for Octopus price — no capacity reserved; re-rank when published"
        )
        changed = True

    if not changed:
        return
    attrs["slots"] = slots
    attrs["battery_plan_summary"] = plan
    attrs["unknown_price_reservation_policy"] = "none"
    attrs["replan_when_price_publishes"] = True
    attrs["no_reserve_reporting_reconciled"] = True
    self._set(_SLOT_SENSOR, slot_state.state, attrs)


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


def _progressive_tomorrow_state_no_reserve(
    self,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Publish zero reserve for a clean, partially published tomorrow horizon."""
    result = _original_progressive_tomorrow_state(self, state)
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


def _plan_summary_rounding(self) -> dict[str, Any]:
    """Normalise reporting-only sub-tolerance residuals to zero coverage gap."""
    result = _original_rounding_plan_summary(self)
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


def install_no_reserve_reporting() -> None:
    """Install the proven current-day publication-gap reporting reconciliation."""
    global _original_no_reserve_annotate
    global _original_no_reserve_plan_summary

    plan_summary = alpha745._plan_summary
    if not getattr(plan_summary, "_kems_no_reserve_reporting", False):
        _original_no_reserve_plan_summary = plan_summary
        _plan_summary_no_reserve._kems_no_reserve_reporting = True
        alpha745._plan_summary = _plan_summary_no_reserve

    annotate = alpha745._annotate_unknown_slot_rows
    if getattr(annotate, "_kems_no_reserve_reporting", False):
        return
    _original_no_reserve_annotate = annotate
    _annotate_unknown_rows_no_reserve._kems_no_reserve_reporting = True
    alpha745._annotate_unknown_slot_rows = _annotate_unknown_rows_no_reserve


def install_tomorrow_publication_reporting() -> None:
    """Install tomorrow no-reserve reporting and residual normalisation."""
    global _original_progressive_tomorrow_state
    global _original_rounding_plan_summary

    progressive = alpha741._progressive_tomorrow_state
    if not getattr(progressive, "_kems_tomorrow_no_reserve_reporting", False):
        _original_progressive_tomorrow_state = progressive
        _progressive_tomorrow_state_no_reserve._kems_tomorrow_no_reserve_reporting = (
            True
        )
        alpha741._progressive_tomorrow_state = _progressive_tomorrow_state_no_reserve

    plan_summary = alpha745._plan_summary
    if getattr(plan_summary, "_kems_publication_rounding", False):
        return
    _original_rounding_plan_summary = plan_summary
    _plan_summary_rounding._kems_publication_rounding = True
    alpha745._plan_summary = _plan_summary_rounding
