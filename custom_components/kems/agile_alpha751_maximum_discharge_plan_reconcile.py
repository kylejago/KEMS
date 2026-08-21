"""Alpha7.51 reconcile maximum-discharge runtime with the rolling price plan.

Alpha7.49 keeps deadline-following dispatch and the economic slot plan aligned,
but its reconciliation returns early once the deadline guard escalates further
to ``maximum_discharge``. That can leave the dashboard saying that the current
half-hour is a hold while the runtime is already exporting battery energy.

Alpha7.51 extends the same plan-rebalance rule to deadline-originated maximum
discharge. Any required export in the current slot is inserted into the rolling
plan and replaces an equal amount from the lowest-value later selected slot.
This changes plan/reporting consistency only; it does not relax the deadline
safety decision or enable real FoxESS hardware writes.
"""

from __future__ import annotations

from typing import Any

from . import agile_alpha717_dispatch as alpha717
from . import agile_alpha749_deadline_plan_coverage as alpha749
from .kems_core import SimulationConfig

_EPSILON = 1e-6


def _dispatch_with_alpha751(
    self,
    state: dict[str, Any],
    plan: dict[str, Any],
    *,
    now,
    config: SimulationConfig,
    tariff,
) -> dict[str, Any]:
    """Reconcile deadline-originated maximum discharge into the rolling plan."""
    targets = alpha751_original_dispatch(
        self,
        state,
        plan,
        now=now,
        config=config,
        tariff=tariff,
    )
    if not isinstance(targets, dict):
        return targets
    if str(targets.get("mode") or "") != "maximum_discharge":
        return targets
    if "deadline_guard_escalated_from" not in targets:
        return targets

    guard = targets.get("deadline_guard")
    guard = dict(guard) if isinstance(guard, dict) else {}
    if not guard.get("deadline_guard_active"):
        return targets

    export_target_kw = max(
        alpha749._number(targets.get("battery_export_target_kw")) or 0.0,
        0.0,
    )
    if export_target_kw <= _EPSILON:
        return targets

    rebalance = alpha749._rebalance_deadline_forced_current_slot(
        state,
        plan,
        now=now,
        export_target_kw=export_target_kw,
    )
    plan["deadline_plan_rebalance"] = rebalance
    targets["deadline_plan_rebalance"] = rebalance
    targets["maximum_discharge_plan_reconciled"] = bool(rebalance.get("applied"))

    guard.update(
        {
            "deadline_guard_active": True,
            "deadline_plan_rebalance": rebalance,
            "maximum_discharge_plan_reconciled": bool(rebalance.get("applied")),
        }
    )
    targets["deadline_guard"] = guard
    self._kems_alpha734_deadline_guard = dict(guard)
    return targets


def install_alpha751_maximum_discharge_plan_reconcile_patch() -> None:
    """Install maximum-discharge plan reconciliation after Alpha7.50."""
    dispatch = alpha717._dispatch_targets
    if getattr(dispatch, "_kems_alpha751_maximum_discharge_plan_reconcile", False):
        return

    global alpha751_original_dispatch
    alpha751_original_dispatch = dispatch
    _dispatch_with_alpha751._kems_alpha751_maximum_discharge_plan_reconcile = True
    alpha717._dispatch_targets = _dispatch_with_alpha751
