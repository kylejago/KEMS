"""Solar-only Feed-in First pilot evidence gate; no write authority.

A favourable Agile price comparison does not establish that a KH7 mode
transition is safe, physically effective, or reversible. This is deliberately
an observational gate over the existing alpha9.123 financial shadow.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

_PILOT_POWER_AGE_SECONDS = 90.0
_PILOT_SOC_AGE_SECONDS = 90.0
_PILOT_MIN_REDIRECT_KW = 0.5
_PILOT_MIN_EXPECTED_BENEFIT_PENCE = 1.0
_PILOT_MIN_MARGIN_PENCE_PER_KWH = 0.75
_POWER_KEYS = (
    "solar_power_kw",
    "house_load_kw",
    "battery_power_kw",
    "grid_import_kw",
    "grid_export_kw",
)


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if isfinite(n) else None


def assess_solar_pilot_readiness(
    *,
    solar_shadow: Mapping[str, Any],
    snapshot: Any,
    work_mode_observation: Mapping[str, Any] | None,
    baseline_restoration_proven: bool = False,
) -> dict[str, Any]:
    """Show missing conditions for a future separately authorised KH7 pilot.

    A Home Assistant `select` observation with source `command_entity` is
    **not** a separate hardware readback. Even if every condition is met,
    the returned result is advisory and never grants a service-call token.
    `baseline_restoration_proven` must come from a future independently
    supervised physical pilot, not this shadow or software prediction.
    """
    reasons: list[str] = []
    candidate = solar_shadow.get("status") == "feed_in_first_candidate"
    if not candidate:
        reasons.append("no_economic_feed_in_first_candidate")
    if solar_shadow.get("hardware_writes") != "forbidden":
        reasons.append("financial_shadow_contract_not_read_only")
    if solar_shadow.get("scope") != "shadow_only":
        reasons.append("financial_shadow_scope_unverified")

    if getattr(snapshot, "ev_connected", None) is not False:
        reasons.append("ev_disconnection_not_independently_confirmed")
    if getattr(snapshot, "ev_charging", None) is not False:
        reasons.append("ev_idle_not_independently_confirmed")
    if getattr(snapshot, "off_peak", None) is not False:
        reasons.append("offpeak_or_unknown_tariff")
    if getattr(snapshot, "tariff_stale_fields", None):
        reasons.append("tariff_source_staleness_reported")
    if getattr(snapshot, "saving_session_active", None) is not False:
        reasons.append("power_down_or_unknown_event")

    ages = getattr(snapshot, "source_age_seconds", None)
    if not isinstance(ages, Mapping):
        reasons.append("physical_power_age_map_missing")
    else:
        for key in _POWER_KEYS:
            age = _finite_number(ages.get(key))
            if age is None or not 0 <= age <= _PILOT_POWER_AGE_SECONDS:
                reasons.append(f"{key}_not_fresh_for_pilot")
        age = _finite_number(ages.get("battery_soc"))
        if age is None or not 0 <= age <= _PILOT_SOC_AGE_SECONDS:
            reasons.append("physical_soc_not_fresh_for_pilot")
    if getattr(snapshot, "stale_fields", None):
        reasons.append("physical_source_staleness_reported")

    flow = solar_shadow.get("physical_solar_flow")
    if (
        not isinstance(flow, Mapping)
        or flow.get("status") != "bounded_physical_inference"
    ):
        reasons.append("pv_to_battery_contribution_not_physically_bounded")

    redirect = _finite_number(solar_shadow.get("bounded_redirectable_solar_kw"))
    advantage = _finite_number(solar_shadow.get("advantage_pence_per_input_kwh"))
    total_benefit = _finite_number(solar_shadow.get("expected_advantage_pence"))
    if redirect is None or redirect < _PILOT_MIN_REDIRECT_KW:
        reasons.append("redirectable_solar_too_small_or_unknown")
    if advantage is None or advantage < _PILOT_MIN_MARGIN_PENCE_PER_KWH:
        reasons.append("economic_margin_too_small_or_unknown")
    if total_benefit is None or total_benefit < _PILOT_MIN_EXPECTED_BENEFIT_PENCE:
        reasons.append("expected_total_benefit_too_small_or_unknown")

    observed = work_mode_observation or {}
    if (
        observed.get("status") != "PASS"
        or observed.get("value") != "Self Use"
        or observed.get("observation_source") != "sensor_readback"
    ):
        reasons.append("independent_kh7_work_mode_readback_not_proven")
    if baseline_restoration_proven is not True:
        reasons.append("independent_baseline_rollback_not_proven")

    return {
        "status": (
            "not_candidate"
            if not candidate
            else (
                "candidate_needs_pilot_evidence"
                if reasons
                else "prerequisites_observed"
            )
        ),
        "financial_candidate": candidate,
        "missing_evidence": reasons,
        "independent_work_mode_observation_source": observed.get("observation_source"),
        "observed_work_mode": observed.get("value"),
        "baseline_restoration_proven": baseline_restoration_proven is True,
        "supervised_pilot_prerequisites_observed": candidate and not reasons,
        "live_mode_switching_enabled": False,
        "hardware_writes": "forbidden",
        "advisory_only": True,
        "require_minimum_dwell_and_hysteresis_before_any_pilot": True,
        "note": (
            "Read-only gate for original-scope solar economics; candidate "
            "price alone is neither independent KH7 readback nor rollback proof."
        ),
    }
