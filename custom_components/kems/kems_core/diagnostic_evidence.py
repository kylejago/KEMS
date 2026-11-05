"""Read-only provenance checks for KEMS diagnostics.

Do not infer supplier settlement, fabricate measured kWh, or feed diagnostic
assessments back into FoxESS, tariff, EV or financial control.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any


def _finite(value: Any) -> float | None:
    """Return a finite numeric source value without inventing a default."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def corroborated_unchanged_sources(
    raw_ages: Mapping[str, Any],
    stale_fields: tuple[str, ...],
    stale_timeout_seconds: int,
) -> dict[str, Any]:
    """Distinguish old raw FoxESS timestamps from truly rejected telemetry.

    The FoxESS provider may accept an unchanged numeric source when another
    numeric sensor from the *same registered device* recently reported.
    This is not a licence to loosen freshness or control-policy thresholds.
    """
    stale = set(stale_fields)
    corroborated = sorted(
        name
        for name, raw_age in raw_ages.items()
        if (age := _finite(raw_age)) is not None
        and age > stale_timeout_seconds
        and name not in stale
    )
    return {
        "raw_age_over_timeout_accepted_by_device_cohort": corroborated,
        "corroboration_policy": "same_foxess_modbus_device_fresh_numeric_sibling",
        "caveat": (
            "An old Home Assistant report timestamp may indicate an unchanged "
            "FoxESS value. Only independent same-device numeric reports can "
            "corroborate it; this does not establish a new physical measurement."
        ),
    }


def actual_export_evidence(
    actual_grid_export_kwh: Any, actual_export_income_pence: Any
) -> dict[str, Any]:
    """Audit two reported actual values without silently repairing either."""
    energy = _finite(actual_grid_export_kwh)
    income = _finite(actual_export_income_pence)
    if energy is None or income is None:
        status = "insufficient_observation"
    elif income > 0.01 and energy <= 0.0005:
        status = "positive_income_without_reported_export_energy"
    elif energy > 0.0005 and income <= 0.01:
        status = "export_energy_without_reported_income"
    else:
        status = "not_flagged"
    return {
        "status": status,
        "reported_actual_grid_export_kwh": energy,
        "reported_actual_export_income_pence": income,
        "source_scopes": (
            "Actual export earnings are valued by tariff-aware physical records; "
            "the observed daily export kWh is reported by the daily simulation. "
            "A mismatch needs source/interval reconciliation before adjusting "
            "either value."
        ),
        "reporting_only": True,
    }


def reward_settlement_evidence(audit: Mapping[str, Any]) -> dict[str, Any]:
    """Separate ROI-included estimates from supplier-confirmed receipts."""
    settled = audit.get("supplier_settlement_available") is True
    return {
        "status": "supplier_verified" if settled else "estimates_awaiting_supplier",
        "roi_included_estimate_pence": _finite(audit.get("included_total_pence")),
        "provisional_partial_pence": _finite(audit.get("provisional_partial_pence")),
        "meter_supported_estimate_pence": _finite(
            audit.get("meter_supported_estimate_pence")
        ),
        "supplier_settled_pence": (
            _finite(audit.get("supplier_settled_pence")) if settled else None
        ),
        "note": (
            "Meter-supported means physically evidenced, not paid or accepted "
            "by Octopus. Provisional credits are incomplete-window estimates; "
            "normal Agile export is not an additional Power Down bonus."
        ),
        "reporting_only": True,
    }
