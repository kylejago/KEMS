"""Read-only provenance checks for KEMS diagnostics.

Do not infer supplier settlement, fabricate measured kWh, or feed diagnostic
assessments back into FoxESS, tariff, EV or financial control.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo


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


def agile_export_interval_audit(
    *,
    records: list[Any],
    agile_state: Mapping[str, Any],
    now: datetime,
    reported_grid_export_kwh: Any,
    reported_income_pence: Any,
    activation_cutoff: Any,
) -> dict[str, Any]:
    """Compare different export scopes by half-hour without changing their values.

    The observed source is integration of instantaneous FoxESS power snapshots,
    not an independent cumulative meter or supplier settlement. The shadow
    settlement is a separate digital-twin estimate, not physical export.
    Use the same start-sample / max-30-minute interval method as
    export_accounting.actual_export_income_pence.
    """
    note = (
        "Read-only: snapshot-integrated grid export and Agile income versus "
        "explicitly marked settled shadow digital-twin slots only (not replay "
        "estimates). Neither is supplier meter settlement; "
        "long sample gaps and boundary crossings are not physical proof."
    )
    if now.tzinfo is None:
        return {"status": "invalid_now", "reporting_only": True, "note": note}
    try:
        cutoff = datetime.fromisoformat(str(activation_cutoff))
    except (TypeError, ValueError):
        cutoff = None
    if cutoff is None or cutoff.tzinfo is None:
        return {
            "status": "paid_export_activation_unverified",
            "reporting_only": True,
            "note": note,
        }

    raw_slots = agile_state.get("today_slots")
    if not isinstance(raw_slots, list):
        return {"status": "no_agile_slots", "reporting_only": True, "note": note}

    rows: list[dict[str, Any]] = []
    intervals: list[tuple[datetime, datetime, dict[str, Any]]] = []
    for source in raw_slots:
        if not isinstance(source, dict):
            continue
        try:
            start = datetime.fromisoformat(str(source.get("valid_from")))
            end = datetime.fromisoformat(str(source.get("valid_to")))
        except (TypeError, ValueError):
            continue
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            continue
        completed = end <= now
        settled = (
            completed
            and source.get("settlement_source") == "settled shadow digital-twin outcome"
        )
        rate = _finite(source.get("rate_pence"))
        model_kwh = _finite(source.get("grid_export_kwh"))
        row = {
            "valid_from": start.isoformat(),
            "valid_to": end.isoformat(),
            "completed": completed,
            "rate_pence_per_kwh": rate,
            "completed_model_grid_export_kwh": model_kwh if completed else None,
            "shadow_grid_export_kwh": model_kwh if settled else None,
            "shadow_income_pence": (
                round(model_kwh * rate, 3)
                if settled and model_kwh is not None and rate is not None
                else None
            ),
            "shadow_source": source.get("settlement_source") if completed else None,
            "snapshot_integrated_export_kwh": 0.0,
            "snapshot_integrated_income_pence": 0.0,
            "sample_pairs": 0,
            "sample_spanned_seconds": 0.0,
            "over_10_minute_gaps": 0,
            "cross_slot_boundary_pairs": 0,
        }
        rows.append(row)
        intervals.append((start, end, row))

    if not rows:
        return {"status": "no_valid_agile_slots", "reporting_only": True, "note": note}

    london = ZoneInfo("Europe/London")
    today = now.astimezone(london).date()
    today_records = sorted(
        (
            item
            for item in records
            if isinstance(getattr(item, "timestamp", None), datetime)
            and item.timestamp.tzinfo is not None
            and item.timestamp.astimezone(london).date() == today
        ),
        key=lambda item: item.timestamp,
    )
    unpriced_positive_pairs = 0
    unmatched_positive_pairs = 0
    for current, following in zip(today_records, today_records[1:], strict=False):
        delta = (following.timestamp - current.timestamp).total_seconds()
        if delta <= 0 or "grid_export_kw" in (
            getattr(current, "stale_fields", ()) or ()
        ):
            continue
        export_kw = _finite(getattr(current, "grid_export_kw", None))
        if export_kw is None or export_kw <= 0:
            continue
        if current.timestamp < cutoff:
            continue
        match = next(
            (
                (end, row)
                for start, end, row in intervals
                if start <= current.timestamp < end
            ),
            None,
        )
        if match is None:
            unmatched_positive_pairs += 1
            continue
        end, row = match
        span = min(delta, 1800.0)
        export_kwh = export_kw * span / 3600.0
        row["sample_pairs"] += 1
        row["sample_spanned_seconds"] += span
        row["snapshot_integrated_export_kwh"] += export_kwh
        if delta > 600:
            row["over_10_minute_gaps"] += 1
        if following.timestamp > end:
            row["cross_slot_boundary_pairs"] += 1
        if row["rate_pence_per_kwh"] is None:
            unpriced_positive_pairs += 1
            row["snapshot_integrated_income_pence"] = None
        elif row["snapshot_integrated_income_pence"] is not None:
            row["snapshot_integrated_income_pence"] += (
                export_kwh * row["rate_pence_per_kwh"]
            )

    for row in rows:
        for name, digits in (
            ("snapshot_integrated_export_kwh", 4),
            ("snapshot_integrated_income_pence", 3),
            ("sample_spanned_seconds", 1),
        ):
            if row[name] is not None:
                row[name] = round(row[name], digits)
        if row["completed"] and row["shadow_grid_export_kwh"] is not None:
            row["shadow_minus_snapshot_kwh"] = round(
                row["shadow_grid_export_kwh"] - row["snapshot_integrated_export_kwh"],
                4,
            )
        else:
            row["shadow_minus_snapshot_kwh"] = None

    completed_rows = [row for row in rows if row["completed"]]
    observed_all_kwh = sum(row["snapshot_integrated_export_kwh"] for row in rows)
    observed_completed_kwh = sum(
        row["snapshot_integrated_export_kwh"] for row in completed_rows
    )
    settled_rows = [
        row for row in completed_rows if row["shadow_grid_export_kwh"] is not None
    ]
    observed_settled_kwh = sum(
        row["snapshot_integrated_export_kwh"] for row in settled_rows
    )
    shadow_completed_kwh = sum(
        row["shadow_grid_export_kwh"] for row in settled_rows
    )
    complete_prices = not (unpriced_positive_pairs or unmatched_positive_pairs)
    observed_income = (
        round(
            sum(row["snapshot_integrated_income_pence"] or 0.0 for row in rows),
            2,
        )
        if complete_prices
        else None
    )
    reported_income = _finite(reported_income_pence)
    return {
        "status": (
            "no_completed_shadow_settlement"
            if not settled_rows
            else "compared"
            if complete_prices
            else "incomplete_price_or_slot_coverage"
        ),
        "reporting_only": True,
        "note": note,
        "scope": "current_london_day_snapshot_samples_vs_completed_digital_twin",
        "completed_slots": len(completed_rows),
        "settled_shadow_slots": len(settled_rows),
        "unsettled_completed_slots": len(completed_rows) - len(settled_rows),
        "snapshot_integrated_export_all_elapsed_kwh": round(observed_all_kwh, 3),
        "snapshot_integrated_export_completed_slots_kwh": round(
            observed_completed_kwh, 3
        ),
        "snapshot_integrated_export_settled_slots_kwh": round(
            observed_settled_kwh, 3
        ),
        "shadow_completed_grid_export_kwh": round(shadow_completed_kwh, 3),
        "shadow_minus_snapshot_completed_kwh": round(
            shadow_completed_kwh - observed_settled_kwh, 3
        ),
        "sample_priced_income_pence": observed_income,
        "reported_actual_export_income_pence": reported_income,
        "sample_income_minus_reported_pence": (
            round(observed_income - reported_income, 2)
            if observed_income is not None and reported_income is not None
            else None
        ),
        "reported_daily_simulation_export_kwh": _finite(reported_grid_export_kwh),
        "unpriced_positive_sample_pairs": unpriced_positive_pairs,
        "unmatched_positive_sample_pairs": unmatched_positive_pairs,
        "long_gap_pairs": sum(row["over_10_minute_gaps"] for row in rows),
        "boundary_crossing_pairs": sum(
            row["cross_slot_boundary_pairs"] for row in rows
        ),
        "rows": rows,
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
