"""Alpha7.50 reconcile no-reserve reporting for clean Agile price gaps.

Alpha7.46/7.47 deliberately stopped reserving battery energy for a verified
Octopus publication gap. A later deadline/maximum-discharge path can still leave
Alpha7.28's bounded reserve evidence populated even though that bounded path is
inactive and the effective provisional reserve is zero. Alpha7.45's row
annotation can then display the stale bounded capacity as if it were still
reserved.

Alpha7.50 changes reporting only. For a verified ``octopus_missing_price`` gap,
when bounded partial dispatch is inactive and the effective provisional reserve
is zero, the battery-plan summary and each waiting slot report no capacity
reserved and explain that the plan will be re-ranked when the price publishes.
Conservative reserve reporting is retained for retrieval failures and for an
actually active bounded-partial path.

Real FoxESS hardware writes remain blocked.
"""

from __future__ import annotations

import math
from typing import Any

from . import agile_alpha745_plan_clarity as alpha745

_EPSILON = 1e-6
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
    return _clean_publication_gap(attrs) and not bounded_active and provisional <= _EPSILON


def _plan_summary_alpha750(self) -> dict[str, Any]:
    """Publish the effective no-reserve policy instead of stale bounded evidence."""
    result = alpha750_original_plan_summary(self)
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


def _annotate_unknown_rows_alpha750(self, plan: dict[str, Any]) -> None:
    """Replace stale per-slot reserve wording after older annotations run."""
    alpha750_original_annotate(self, plan)

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


def install_alpha750_no_reserve_reporting_patch() -> None:
    """Install reporting reconciliation after Alpha7.49."""
    global alpha750_original_annotate
    global alpha750_original_plan_summary

    plan_summary = alpha745._plan_summary
    if not getattr(plan_summary, "_kems_alpha750_no_reserve_reporting", False):
        alpha750_original_plan_summary = plan_summary
        _plan_summary_alpha750._kems_alpha750_no_reserve_reporting = True
        alpha745._plan_summary = _plan_summary_alpha750

    annotate = alpha745._annotate_unknown_slot_rows
    if getattr(annotate, "_kems_alpha750_no_reserve_reporting", False):
        return
    alpha750_original_annotate = annotate
    _annotate_unknown_rows_alpha750._kems_alpha750_no_reserve_reporting = True
    alpha745._annotate_unknown_slot_rows = _annotate_unknown_rows_alpha750
