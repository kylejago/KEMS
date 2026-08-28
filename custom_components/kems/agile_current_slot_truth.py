"""Reconcile the active Agile slot with the current rolling plan.

Future half-hour rows carry forecast actions, export allocations and end-SOC
values. Once a row becomes the active slot those forecast presentation fields
must not survive a rolling replan that has changed the current decision. This
layer makes the current row describe the same allocation and SOC authority as
the rolling planner without changing replay accounting or hardware control.

Real FoxESS hardware writes remain blocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import agile_rolling_replan as rolling
from .kems_core import SimulationConfig
from .tariff import TariffSettings

_EPSILON = 1e-6


def _number(value: Any) -> float | None:
    """Return a finite float when possible."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _datetime(value: Any) -> datetime | None:
    """Parse one ISO timestamp as UTC."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value)).astimezone(UTC)
    except ValueError:
        return None


def _reconcile_current_slot(
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now: datetime,
) -> None:
    """Replace stale future-row presentation with the current rolling decision."""
    if not plan.get("available"):
        return

    slots = state.get("today_slots")
    if not isinstance(slots, list):
        return

    soc = _number(plan.get("simulated_soc_percent"))
    target = _number(plan.get("target_soc_percent"))
    now_utc = now.astimezone(UTC)

    for slot in slots:
        if not isinstance(slot, dict):
            continue
        start = _datetime(slot.get("valid_from"))
        end = _datetime(slot.get("valid_to"))
        if start is None or end is None or not (start <= now_utc < end):
            continue

        allocation = max(
            _number(slot.get("rolling_planned_battery_export_kwh")) or 0.0,
            0.0,
        )
        slot["rolling_current_slot"] = True
        slot["current_slot_plan_reconciled"] = True
        slot["current_slot_plan_reconciled_at"] = now.isoformat()
        slot["current_soc_percent"] = round(soc, 1) if soc is not None else None

        # Preserve the old future forecast as diagnostics, but do not publish it
        # as this active slot's end-SOC truth after the slot has already begun.
        stale_end_soc = _number(slot.get("ending_soc_percent"))
        if stale_end_soc is not None:
            slot["pre_replan_forecast_ending_soc_percent"] = round(stale_end_soc, 1)
        slot["ending_soc_percent"] = None

        slot["battery_export_kwh"] = round(allocation, 3)
        if allocation > _EPSILON:
            action = str(
                slot.get("rolling_action") or "planned battery export — rolling replan"
            )
        elif soc is not None and target is not None and soc <= target + _EPSILON:
            action = "house first — target reached; no battery export planned"
        else:
            action = "house first — no battery export planned"

        slot["rolling_action"] = action
        slot["actions"] = [action]
        break


def _rolling_plan_with_current_slot_truth(
    self,
    state: dict[str, Any],
    *,
    now: datetime,
    config: SimulationConfig,
    tariff: TariffSettings,
) -> dict[str, Any]:
    """Run the canonical rolling planner then reconcile its active row."""
    plan = _original_rolling_plan(
        self,
        state,
        now=now,
        config=config,
        tariff=tariff,
    )
    if isinstance(plan, dict):
        _reconcile_current_slot(state, plan, now=now)
    return plan


def install_current_slot_truth() -> None:
    """Install active-slot presentation reconciliation exactly once."""
    global _original_rolling_plan

    planner = rolling._rolling_plan
    if getattr(planner, "_kems_current_slot_truth", False):
        return

    _original_rolling_plan = planner
    _rolling_plan_with_current_slot_truth._kems_current_slot_truth = True
    rolling._rolling_plan = _rolling_plan_with_current_slot_truth
