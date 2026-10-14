"""Live paid Agile planning authority from bounded FoxESS physical energy.

This never rewrites the independent digital twin or historical comparison.
The coordinator supplies a single-scan physical evidence object before the
Agile runtime builds its rolling, deadline and forecast plans. Every caller
uses the exact same proof as the final hardware export reserve guard.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

from .kems_core import SimulationConfig
from .kems_core.agile_live_reserve import (
    physical_energy_evidence_matches_snapshot,
)


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (ValueError, TypeError):
        return None
    return n if isfinite(n) else None


def physical_planning_soc(
    manager: Any,
    *,
    now: datetime,
    config: SimulationConfig,
) -> tuple[float | None, dict[str, object]]:
    """Return a conservative live SOC for dispatch, or explicit unavailability.

    The only physical authority is a same-scan, same-SOC FoxESS energy proof,
    with fresh directly measured battery power and source freshness.
    In case of any gap or mismatch the caller must keep the twin independent
    and let the physical export guard fail closed.
    """
    reason = "no verified live physical energy evidence"
    context = getattr(manager, "_kems_physical_planning_context", None)
    if not isinstance(context, dict):
        return None, {"available": False, "reason": reason}
    snapshot = context.get("snapshot")
    evidence = context.get("evidence")
    control = context.get("control")
    if snapshot is None or evidence is None or control is None:
        return None, {"available": False, "reason": reason}
    if (
        not physical_energy_evidence_matches_snapshot(
            evidence,
            snapshot,
            control,
            now=now,
        )
        or snapshot.cheap_period_confirmed
        or snapshot.saving_session_active
    ):
        return None, {
            "available": False,
            "reason": "physical source freshness, continuity or priority gate failed",
        }
    cap = _number(config.battery_capacity_kwh)
    energy = _number(evidence.lower_bound_kwh)
    if cap is None or cap <= 0 or energy is None or not 0 <= energy <= cap:
        return None, {
            "available": False,
            "reason": "invalid physical lower bound or configured capacity",
        }
    soc = 100.0 * energy / cap
    return soc, {
        "available": True,
        "source": "verified FoxESS physical energy lower bound",
        "planning_soc_percent": round(soc, 3),
        "physical_energy_lower_bound_kwh": round(energy, 3),
        "physical_soc_report_percent": round(snapshot.battery_soc, 3),
        "physical_soc_anchor": evidence.source_soc_at.isoformat(),
        "physical_samples": evidence.samples,
        "worst_case_gap_kwh": round(evidence.worst_case_gap_kwh, 3),
        "pessimistic_discharge_kwh": round(
            evidence.pessimistic_discharge_kwh, 3
        ),
        "replay_simulation_soc_preserved": True,
        "scope": "paid_agile_live_control_only",
    }
