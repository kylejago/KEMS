"""Keep settled current-day SOC and deadline diagnostics on one authority.

Current-day shadow settlement can move the canonical simulated SOC away from the
older day replay.  The rolling planner is regenerated from that settled SOC, so
its deadline guard is the authoritative physical view after reconciliation.
This canonical Alpha8 owner mirrors that fresh deadline evidence back into the
Today Agile summary instead of leaving headline deadline fields based on the
pre-settlement replay SOC.

Reporting reconciliation only: it does not change dispatch, tariffs, event
priority, reserve policy, commissioning, or hardware writes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .agile_live_solar_soc_continuity import (
    LiveSolarSocContinuityAgileSmartExportManager,
)
from .kems_core import SimulationConfig

_EPSILON = 1e-6


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _today_agile(state: dict[str, Any]) -> dict[str, Any] | None:
    periods = state.get("periods")
    today = periods.get("today") if isinstance(periods, dict) else None
    agile = today.get("agile_smart_export") if isinstance(today, dict) else None
    return agile if isinstance(agile, dict) else None


def _rolling_deadline_guard(state: dict[str, Any]) -> dict[str, Any] | None:
    plan = state.get("rolling_export_plan")
    if not isinstance(plan, dict):
        return None
    guard = plan.get("deadline_guard")
    return guard if isinstance(guard, dict) else None


def rebase_day_summary_deadline_from_rolling(
    state: dict[str, Any],
    *,
    config: SimulationConfig | None,
) -> dict[str, Any]:
    """Rebase Today deadline metrics from the post-settlement rolling guard."""
    agile = _today_agile(state)
    guard = _rolling_deadline_guard(state)
    if agile is None or guard is None or not guard.get("available"):
        diagnostic = {
            "active": False,
            "applied": False,
            "reason": "settled Today Agile summary or rolling deadline guard unavailable",
            "reporting_only": True,
            "hardware_writes": "blocked",
        }
        state["deadline_settlement_reconciliation"] = diagnostic
        return diagnostic

    settled_soc = _number(agile.get("ending_soc_percent"))
    guard_soc = _number(guard.get("simulated_soc_percent"))
    required = _number(guard.get("required_discharge_kwh"))
    remaining = _number(guard.get("solar_aware_remaining_capacity_kwh"))
    margin = _number(guard.get("solar_aware_deadline_margin_kwh"))
    required_average = _number(guard.get("required_average_discharge_kw"))
    minimum_reachable = _number(guard.get("minimum_reachable_soc_percent"))
    target = _number(guard.get("target_soc_percent"))
    reachable = bool(guard.get("target_physically_reachable_now"))

    if settled_soc is None or guard_soc is None or required is None or remaining is None:
        diagnostic = {
            "active": True,
            "applied": False,
            "reason": "rolling deadline guard lacks finite settled deadline evidence",
            "reporting_only": True,
            "hardware_writes": "blocked",
        }
        state["deadline_settlement_reconciliation"] = diagnostic
        return diagnostic

    # A freshly regenerated rolling plan should already be on the settled SOC.
    # Keep the mismatch explicit rather than silently inventing a replacement.
    soc_aligned = abs(settled_soc - guard_soc) <= 0.02
    if required <= 0.01:
        status = "Target reached"
    elif reachable:
        status = "Reachable"
    else:
        status = "Physically unreachable"

    effective_kw = None
    if isinstance(config, SimulationConfig):
        effective_kw = min(
            max(float(config.max_discharge_kw), 0.0),
            max(float(config.inverter_limit_kw), 0.0),
        )

    agile.update(
        {
            "deadline_target_soc_percent": round(target, 2) if target is not None else None,
            "deadline_time": guard.get("deadline"),
            "deadline_status": status,
            "deadline_effective_discharge_kw": (
                round(effective_kw, 3) if effective_kw is not None else None
            ),
            "deadline_required_discharge_kwh": round(required, 3),
            "deadline_max_remaining_discharge_kwh": round(remaining, 3),
            "deadline_margin_kwh": round(
                margin if margin is not None else remaining - required,
                3,
            ),
            "deadline_required_average_kw": (
                round(required_average, 3) if required_average is not None else None
            ),
            "deadline_minimum_reachable_soc_percent": (
                round(minimum_reachable, 2)
                if minimum_reachable is not None
                else None
            ),
            "deadline_soc_authority": "settled current-day digital-twin SOC",
            "deadline_metrics_source": "post-settlement rolling deadline guard",
        }
    )

    diagnostic = {
        "active": True,
        "applied": True,
        "settled_soc_percent": round(settled_soc, 3),
        "rolling_guard_soc_percent": round(guard_soc, 3),
        "soc_aligned": soc_aligned,
        "target_soc_percent": round(target, 2) if target is not None else None,
        "required_discharge_kwh": round(required, 3),
        "remaining_discharge_capacity_kwh": round(remaining, 3),
        "deadline_margin_kwh": round(
            margin if margin is not None else remaining - required,
            3,
        ),
        "minimum_reachable_soc_percent": (
            round(minimum_reachable, 2) if minimum_reachable is not None else None
        ),
        "deadline_status": status,
        "happy_hour_deadline_protected": bool(
            guard.get("happy_hour_deadline_protected")
        ),
        "happy_hour_deadline_obligation_kwh": round(
            max(_number(guard.get("happy_hour_deadline_obligation_kwh")) or 0.0, 0.0),
            3,
        ),
        "reporting_only": True,
        "hardware_writes": "blocked",
    }
    state["deadline_settlement_reconciliation"] = diagnostic
    return diagnostic


class DeadlineSettlementConsistencyAgileSmartExportManager(
    LiveSolarSocContinuityAgileSmartExportManager
):
    """Own post-settlement Today deadline diagnostic consistency."""

    def reconcile_current_day_settlements(
        self,
        *,
        settled_half_hours: list[dict[str, Any]],
        now: datetime,
    ) -> dict[str, Any]:
        super().reconcile_current_day_settlements(
            settled_half_hours=settled_half_hours,
            now=now,
        )
        config = getattr(self, "_rolling_config", None)
        rebase_day_summary_deadline_from_rolling(
            self._state,
            config=config if isinstance(config, SimulationConfig) else None,
        )
        self._publish(self._state)
        return self.state
