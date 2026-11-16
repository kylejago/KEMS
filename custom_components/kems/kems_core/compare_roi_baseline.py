"""Safely reconcile today's no-system comparison to the actual ROI ledger.

Presentation only. Never substitutes counterfactual scenario import energy,
rewrites the financial ledger, or changes inverter and EV dispatch.
"""

from __future__ import annotations

from math import isfinite
from typing import Any


def _money(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def compare_no_system_cost_today(data: Any) -> dict[str, Any]:
    """Select a source-consistent bill counterfactual or expose the fallback.

    Compare's independent scenario replay and ROI's measured history use
    different time/sample resampling. Use the ROI baseline only when its
    import/export, current-day date, and daily ledger exactly reconcile;
    otherwise keep the original scenario amount with explicit provenance.
    Electricity standing charge comes from the same scenario in both cases.
    Gas is added separately from Live on the dashboard.
    """
    scenario = data.scenarios.scenario("no_system")
    if scenario is None:
        return {
            "total_cost_pence": None,
            "comparison_cost_basis": "unavailable",
            "comparison_basis_reason": "no_system_scenario_unavailable",
        }
    replay = _money(scenario.total_cost_pence)
    result: dict[str, Any] = {
        "total_cost_pence": round(replay, 2) if replay is not None else None,
        "comparison_cost_basis": "scenario_replay_unreconciled",
        "comparison_basis_reason": "roi_daily_evidence_unavailable",
        "scenario_replay_cost_pence": round(replay, 2) if replay is not None else None,
        "roi_baseline_import_cost_pence": None,
        "roi_vs_replay_difference_pence": None,
    }
    if not scenario.ready or replay is None:
        result["comparison_basis_reason"] = "no_system_scenario_not_ready"
        return result

    sim = data.simulation
    period = data.periods.get("today")
    if not sim.ready or period is None:
        return result

    timestamp = getattr(data.snapshot, "timestamp", None)
    if (
        timestamp is None
        or getattr(period, "start_date", None) != timestamp.date()
        or getattr(period, "end_date", None) != timestamp.date()
        or getattr(period, "days_included", 0) != 1
    ):
        result["comparison_basis_reason"] = "daily_rollover_or_period_mismatch"
        return result

    values = [
        _money(sim.baseline_no_system_cost_pence),
        _money(sim.actual_import_cost_pence),
        _money(sim.actual_export_income_pence),
        _money(period.import_cost_pence),
        _money(period.export_income_pence),
        _money(period.actual_avoided_import_value_pence),
        _money(period.actual_system_value_pence),
        _money(scenario.standing_charge_pence),
    ]
    if any(value is None for value in values):
        result["comparison_basis_reason"] = "nonfinite_or_missing_financial_evidence"
        return result
    (
        baseline,
        sim_import,
        sim_export,
        day_import,
        day_export,
        avoided,
        actual_value,
        standing,
    ) = values

    # Penny-level consistency: never replace an independently sampled model
    # with ROI values from a different day or incomplete financial scan.
    if any(
        abs(delta) > 0.025
        for delta in (
            sim_import - day_import,
            sim_export - day_export,
            baseline - (day_import + avoided),
            actual_value - (avoided + day_export),
        )
    ):
        result["comparison_basis_reason"] = "roi_and_live_ledger_not_synchronised"
        return result

    effective = round(baseline + standing, 2)
    result.update(
        total_cost_pence=effective,
        comparison_cost_basis="roi_meter_sampled_baseline",
        comparison_basis_reason="matched_actual_import_export_and_daily_ledger",
        roi_baseline_import_cost_pence=round(baseline, 2),
        roi_vs_replay_difference_pence=round(effective - replay, 2),
    )
    return result
