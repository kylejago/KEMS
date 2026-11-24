"""Read-only provenance checks for KEMS diagnostics.

Do not infer supplier settlement, fabricate measured kWh, or feed diagnostic
assessments back into FoxESS, tariff, EV or financial control.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
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
    observations: dict[str, dict[str, Any]] = {}
    for name, raw_age in sorted(raw_ages.items()):
        age = _finite(raw_age)
        if name in stale:
            status = "rejected_as_stale"
        elif age is None or age < 0:
            status = "raw_timestamp_missing"
        elif age > stale_timeout_seconds:
            status = "accepted_unchanged_by_device_cohort_not_remeasured"
        else:
            status = "raw_timestamp_within_limit"
        observations[name] = {
            "raw_report_age_seconds": round(age, 1) if age is not None else None,
            "status": status,
            # A recent Home Assistant report timestamp is not an independent
            # physical measurement. Keep the legacy boolean truthful while
            # exposing exactly the recency fact that can be supported.
            "raw_report_within_freshness_limit": status == "raw_timestamp_within_limit",
            "physical_remeasurement_proven": False,
        }
    if stale:
        overall = "one_or_more_sources_rejected_stale"
    elif corroborated:
        overall = "unchanged_source_timestamps_old_but_cohort_accepted"
    else:
        overall = "raw_report_ages_within_limit"
    return {
        "raw_age_over_timeout_accepted_by_device_cohort": corroborated,
        "raw_report_provenance": {
            "status": overall,
            "raw_timeout_seconds": stale_timeout_seconds,
            "fields": observations,
            "old_raw_timestamp_fields": corroborated,
            "controller_stale_fields": sorted(stale),
            "reconfirmed_independent_physical_measurement_for_old_values": False,
            "changes_control_freshness_or_foxess_commands": False,
        },
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
    completed_power_down: Mapping[str, Any] | None = None,
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

    # A previously completed, physically verified Power Down may overlap the
    # sample-versus-shadow comparison. This is context for audit triage only:
    # overlap neither proves causation nor changes export income or dispatch.
    verified_power_down_interval: tuple[datetime, datetime] | None = None
    if (
        isinstance(completed_power_down, Mapping)
        and completed_power_down.get("completed_successfully") is True
        and completed_power_down.get("physical_export_verified") is True
    ):
        try:
            event_start = datetime.fromisoformat(
                str(completed_power_down.get("session_start"))
            )
            event_end = datetime.fromisoformat(
                str(completed_power_down.get("session_end"))
            )
        except (TypeError, ValueError):
            pass
        else:
            if (
                event_start.tzinfo is not None
                and event_end.tzinfo is not None
                and event_end > event_start
            ):
                verified_power_down_interval = (event_start, event_end)

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
            "verified_power_down_window_overlap": (
                verified_power_down_interval is not None
                and min(end, verified_power_down_interval[1])
                > max(start, verified_power_down_interval[0])
            ),
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
            "sample_observed_seconds": 0.0,
            "over_10_minute_gaps": 0,
            "cross_slot_boundary_pairs": 0,
            "boundary_reference_export_kwh": 0.0,
            "boundary_reference_income_pence": 0.0,
            "boundary_reference_spanned_seconds": 0.0,
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
    # Time coverage is distinct from *positive export* time. All valid
    # observations, including 0kW, prove source visibility for an interval.
    # Do not count missing/stale source readings as observed or invent kWh.
    for current, following in zip(today_records, today_records[1:], strict=False):
        delta = (following.timestamp - current.timestamp).total_seconds()
        power = _finite(getattr(current, "grid_export_kw", None))
        if (
            delta <= 0
            or power is None
            or power < 0
            or "grid_export_kw" in (getattr(current, "stale_fields", ()) or ())
        ):
            continue
        capped_end = current.timestamp + timedelta(seconds=min(delta, 1800.0))
        for start, end, row in intervals:
            seconds = (
                min(capped_end, end, now) - max(start, current.timestamp)
            ).total_seconds()
            if seconds > 0:
                row["sample_observed_seconds"] += seconds

    unpriced_positive_pairs = 0
    unmatched_positive_pairs = 0
    boundary_reference_unmatched_kwh = 0.0
    boundary_reference_unpriced_pairs = 0
    boundary_reference_reallocated_kwh = 0.0
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
        # Independent diagnostic reference: allocate *the same* start-sample
        # power over the actual elapsed timestamp overlaps, including a
        # half-hour boundary. Do not change the existing tariff-priced
        # accounting convention or the original settled-shadow comparison.
        capped_end = current.timestamp + timedelta(seconds=span)
        allocated_seconds = 0.0
        for other_start, other_end, reference_row in intervals:
            reference_seconds = (
                min(capped_end, other_end) - max(current.timestamp, other_start)
            ).total_seconds()
            if reference_seconds <= 0:
                continue
            allocated_seconds += reference_seconds
            reference_kwh = export_kw * reference_seconds / 3600.0
            reference_row["boundary_reference_export_kwh"] += reference_kwh
            reference_row["boundary_reference_spanned_seconds"] += reference_seconds
            reference_rate = reference_row["rate_pence_per_kwh"]
            if reference_rate is None:
                boundary_reference_unpriced_pairs += 1
                reference_row["boundary_reference_income_pence"] = None
            elif reference_row["boundary_reference_income_pence"] is not None:
                reference_row["boundary_reference_income_pence"] += (
                    reference_kwh * reference_rate
                )
            if reference_row is not row:
                boundary_reference_reallocated_kwh += reference_kwh
        if allocated_seconds < span:
            boundary_reference_unmatched_kwh += (
                export_kw * (span - allocated_seconds) / 3600.0
            )

    for row in rows:
        for name, digits in (
            ("snapshot_integrated_export_kwh", 4),
            ("snapshot_integrated_income_pence", 3),
            ("sample_spanned_seconds", 1),
            ("sample_observed_seconds", 1),
            ("boundary_reference_export_kwh", 4),
            ("boundary_reference_income_pence", 3),
            ("boundary_reference_spanned_seconds", 1),
        ):
            if row[name] is not None:
                row[name] = round(row[name], digits)
        duration = (
            datetime.fromisoformat(row["valid_to"])
            - datetime.fromisoformat(row["valid_from"])
        ).total_seconds()
        observed = min(row["sample_observed_seconds"], duration)
        row["sample_coverage_percent"] = (
            round(100.0 * observed / duration, 1) if duration > 0 else None
        )
        row["unobserved_seconds"] = round(max(duration - observed, 0.0), 1)
        row["positive_export_sample_seconds"] = row["sample_spanned_seconds"]
        row["sample_coverage_status"] = (
            "incomplete_sample_coverage"
            if row["completed"] and row["sample_coverage_percent"] < 95.0
            else (
                "observed_at_least_95_percent"
                if row["completed"]
                else "slot_not_complete"
            )
        )
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
    shadow_completed_kwh = sum(row["shadow_grid_export_kwh"] for row in settled_rows)
    complete_prices = not (unpriced_positive_pairs or unmatched_positive_pairs)
    observed_income = (
        round(
            sum(row["snapshot_integrated_income_pence"] or 0.0 for row in rows),
            2,
        )
        if complete_prices
        else None
    )
    boundary_reference_priced_income = (
        round(
            sum(row["boundary_reference_income_pence"] or 0.0 for row in rows),
            2,
        )
        if not boundary_reference_unpriced_pairs
        and boundary_reference_unmatched_kwh <= 0.000001
        else None
    )
    boundary_reference_completed_kwh = sum(
        row["boundary_reference_export_kwh"] for row in completed_rows
    )
    boundary_reference_settled_kwh = sum(
        row["boundary_reference_export_kwh"] for row in settled_rows
    )
    # Rank model-versus-sampled export differences without promoting either
    # source to supplier settlement. Positive/negative offsets can cancel in
    # the daily net, so retain the absolute discrepancy as separate evidence.
    ranked_variances = sorted(
        settled_rows,
        key=lambda row: (
            -abs(row["shadow_minus_snapshot_kwh"]),
            row["valid_from"],
        ),
    )
    top_variances = [
        {
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "shadow_minus_snapshot_kwh": row["shadow_minus_snapshot_kwh"],
            "verified_power_down_window_overlap": row[
                "verified_power_down_window_overlap"
            ],
            "shadow_minus_boundary_reference_kwh": round(
                row["shadow_grid_export_kwh"] - row["boundary_reference_export_kwh"],
                4,
            ),
            "snapshot_export_kwh": row["snapshot_integrated_export_kwh"],
            "shadow_export_kwh": row["shadow_grid_export_kwh"],
            "sample_coverage_percent": row["sample_coverage_percent"],
            "unobserved_seconds": row["unobserved_seconds"],
            "evidence_limitation_flags": (
                (
                    ["incomplete_observation_coverage"]
                    if row["sample_coverage_percent"] < 95.0
                    else []
                )
                + (
                    ["cross_slot_sample_pair"]
                    if row["cross_slot_boundary_pairs"]
                    else []
                )
                + (["over_ten_minute_sample_gap"] if row["over_10_minute_gaps"] else [])
            ),
        }
        for row in ranked_variances[:5]
    ]
    # Top ordinary Agile differences must not be hidden behind a higher-ranked
    # physically verified Power Down window. Restrict to explicitly settled
    # shadow rows, and keep measurement quality visible for every candidate.
    non_power_down_ranked = [
        row for row in ranked_variances if not row["verified_power_down_window_overlap"]
    ]
    top_non_power_down = [
        {
            "valid_from": row["valid_from"],
            "valid_to": row["valid_to"],
            "shadow_minus_snapshot_kwh": row["shadow_minus_snapshot_kwh"],
            "sample_coverage_percent": row["sample_coverage_percent"],
            "unobserved_seconds": row["unobserved_seconds"],
            "cross_slot_boundary_pairs": row["cross_slot_boundary_pairs"],
            "over_10_minute_gaps": row["over_10_minute_gaps"],
            "independent_supplier_meter_verified": False,
        }
        for row in non_power_down_ranked[:5]
    ]
    reported_income = _finite(reported_income_pence)
    return {
        "status": (
            "no_completed_shadow_settlement"
            if not settled_rows
            else "compared" if complete_prices else "incomplete_price_or_slot_coverage"
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
        "snapshot_integrated_export_settled_slots_kwh": round(observed_settled_kwh, 3),
        "shadow_completed_grid_export_kwh": round(shadow_completed_kwh, 3),
        "shadow_minus_snapshot_completed_kwh": round(
            shadow_completed_kwh - observed_settled_kwh, 3
        ),
        "verified_power_down_overlap_settled_slots": sum(
            row["verified_power_down_window_overlap"] for row in settled_rows
        ),
        "verified_power_down_overlap_shadow_minus_sample_kwh": round(
            sum(
                row["shadow_minus_snapshot_kwh"]
                for row in settled_rows
                if row["verified_power_down_window_overlap"]
            ),
            3,
        ),
        "non_power_down_shadow_minus_sample_kwh": round(
            sum(
                row["shadow_minus_snapshot_kwh"]
                for row in settled_rows
                if not row["verified_power_down_window_overlap"]
            ),
            3,
        ),
        "settled_variance_absolute_sum_kwh": round(
            sum(abs(row["shadow_minus_snapshot_kwh"]) for row in settled_rows), 3
        ),
        "settled_variance_positive_sum_kwh": round(
            sum(max(row["shadow_minus_snapshot_kwh"], 0.0) for row in settled_rows),
            3,
        ),
        "settled_variance_negative_sum_kwh": round(
            sum(min(row["shadow_minus_snapshot_kwh"], 0.0) for row in settled_rows),
            3,
        ),
        "top_settled_variance_rows": top_variances,
        "top_settled_variance_rows_omitted": max(len(ranked_variances) - 5, 0),
        "non_power_down_completed_settled_slots": len(non_power_down_ranked),
        "top_non_power_down_variance_rows": top_non_power_down,
        "top_non_power_down_variance_rows_omitted": max(
            len(non_power_down_ranked) - len(top_non_power_down), 0
        ),
        "variance_triage_note": (
            "Ranked read-only digital-twin minus power-sample differences. "
            "Flags identify possible evidence limitations, not root causes; "
            "neither source is an independent supplier export meter. "
            "Verified Power Down overlap is context, not attribution."
        ),
        "sample_priced_income_pence": observed_income,
        "boundary_reference_export_completed_kwh": round(
            boundary_reference_completed_kwh, 3
        ),
        "boundary_reference_export_settled_kwh": round(
            boundary_reference_settled_kwh, 3
        ),
        "boundary_reference_shadow_minus_export_kwh": round(
            shadow_completed_kwh - boundary_reference_settled_kwh, 3
        ),
        "boundary_reference_priced_income_pence": boundary_reference_priced_income,
        "boundary_reference_unmatched_kwh": round(boundary_reference_unmatched_kwh, 4),
        "boundary_reference_unpriced_pairs": boundary_reference_unpriced_pairs,
        "boundary_reference_reallocated_kwh": round(
            boundary_reference_reallocated_kwh, 4
        ),
        "boundary_reference_note": (
            "Diagnostic only: prorates the same instantaneous starting power "
            "sample by overlapping published half-hours. This is NOT an "
            "independent physical or Octopus settlement measurement, and "
            "does not change KEMS billed earnings or control."
        ),
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
        "settled_slots_with_incomplete_sample_coverage": sum(
            row["sample_coverage_status"] == "incomplete_sample_coverage"
            for row in settled_rows
        ),
        "settled_slots_unobserved_seconds": round(
            sum(row["unobserved_seconds"] for row in settled_rows), 1
        ),
        "sample_coverage_note": (
            "Diagnostic observed-time coverage counts valid same-day FoxESS "
            "power readings even when grid export is zero, and excludes stale "
            "samples. Positive export sample spans are a different metric; "
            "neither is an independent export meter or Octopus settlement. "
            "Missing elapsed time is not evidence of zero export."
        ),
        "boundary_crossing_pairs": sum(
            row["cross_slot_boundary_pairs"] for row in rows
        ),
        "rows": rows,
    }


def agile_current_export_execution_observation(
    *,
    snapshot: Any,
    control: Any,
    agile_state: Mapping[str, Any],
    physical_guard: Mapping[str, Any],
) -> dict[str, Any]:
    """One-scan plan / permitted request / FoxESS CT observation.

    Never treat a one-scan mismatch as a failed dispatch; inverter ramping,
    house consumption and solar export all prevent strict kW equality.
    No new hardware write authority or control policy.
    """
    plan = agile_state.get("rolling_export_plan")
    if not isinstance(plan, dict) or not plan.get("available"):
        return {
            "status": "no_rolling_plan",
            "reporting_only": True,
            "physical_dispatch_verified": False,
        }

    requested = _finite(plan.get("current_battery_export_target_kw"))
    guard_requested = _finite(physical_guard.get("requested_export_kw"))
    permitted = _finite(physical_guard.get("permitted_export_kw"))
    desired = _finite(getattr(control, "desired_battery_export_power_kw", None))
    observed = _finite(getattr(snapshot, "grid_export_kw", None))
    imported = _finite(getattr(snapshot, "grid_import_kw", None))
    if (
        requested is None
        or desired is None
        or observed is None
        or observed < 0
        or imported is None
        or imported < 0
    ):
        status = "missing_or_invalid_current_evidence"
    elif not getattr(control, "commands_permitted", False):
        status = "control_gate_not_authorised"
    elif requested <= 0.15 and desired <= 0.15:
        status = (
            "grid_export_observed_without_battery_request"
            if observed > 0.15
            else "waiting_for_selected_agile_export"
        )
    elif permitted is not None and permitted <= 0.15 and requested > 0.15:
        status = "physical_reserve_guard_blocked_request"
    elif desired <= 0.15:
        status = "planner_request_not_in_final_control"
    elif observed <= 0.15:
        status = "authorised_export_not_yet_observed_in_single_snapshot"
    else:
        status = "grid_export_observed"

    routing = agile_state.get("current_routing_snapshot")
    routing = routing if isinstance(routing, Mapping) else {}
    proof = physical_guard.get("physical_energy_evidence")
    proof = proof if isinstance(proof, Mapping) else {}
    physical_soc = _finite(getattr(snapshot, "battery_soc", None))
    snapshot_at = getattr(snapshot, "timestamp", None)
    bound = _finite(physical_guard.get("physical_soc_lower_bound_percent"))
    # The guard owns this proof, not the earlier advisory routing publisher.
    # A new SOC anchor is as valid as continuity when accepted by the guard.
    physical_same_scan = bool(
        snapshot_at is not None
        and physical_guard.get("physical_bound_snapshot_at") == snapshot_at.isoformat()
        and physical_soc is not None
        and _finite(physical_guard.get("physical_soc_percent")) == physical_soc
        and bound is not None
        and 0.0 <= bound <= physical_soc <= 100.0
    )
    ledger_accepted = bool(
        physical_same_scan
        and physical_guard.get("physical_bound_ledger_accepted") is True
    )
    twin_soc = _finite(plan.get("simulated_soc_percent"))
    soc_difference = (
        round(twin_soc - physical_soc, 3)
        if twin_soc is not None and physical_soc is not None
        else None
    )
    return {
        "status": status,
        "reporting_only": True,
        "physical_dispatch_verified": False,
        "routing_provenance": {
            "proposal_scope": "pre_guard_digital_twin_not_hardware_command",
            "proposal_battery_export_kw": _finite(routing.get("battery_export_kw")),
            "proposal_grid_export_kw": _finite(routing.get("grid_export_kw")),
            "guard_permitted_battery_export_kw": permitted,
            "final_desired_battery_export_kw": desired,
            "authorised_battery_export_kw": (
                desired if getattr(control, "commands_permitted", False) else None
            ),
            "final_desired_total_discharge_kw": _finite(
                getattr(control, "desired_total_discharge_power_kw", None)
            ),
            "measured_grid_export_kw": observed,
            "measured_grid_import_kw": imported,
            "legacy_routing_schema_version": routing.get("version"),
            "physical_soc_percent": physical_soc,
            "physical_lower_bound_soc_percent": (bound if physical_same_scan else None),
            "physical_lower_bound_same_scan": physical_same_scan,
            "physical_lower_bound_ledger_accepted": ledger_accepted,
            "physical_lower_bound_basis": (
                physical_guard.get("soc_freshness_basis")
                if physical_same_scan
                else None
            ),
            "physical_energy_tracker_status": proof.get("status"),
            "physical_bound_guard_at": (
                physical_guard.get("physical_bound_guard_at")
                if physical_same_scan
                else None
            ),
            "independent_twin_soc_percent": twin_soc,
            "twin_minus_physical_soc_percentage_points": soc_difference,
            "guarded_conditional_arrival_soc_percent": _finite(
                plan.get("forecast_path_reconciled_ending_soc_percent")
            ),
            "theoretical_arrival_soc_percent": _finite(
                plan.get("forecast_path_theoretical_ending_soc_percent")
            ),
            "arrival_guaranteed": False,
            "hardware_writes": "forbidden",
        },
        "observation_timestamp": (
            getattr(snapshot, "timestamp", None).isoformat()
            if getattr(snapshot, "timestamp", None) is not None
            else None
        ),
        "rolling_plan_requested_export_kw": requested,
        "physical_guard_requested_export_kw": guard_requested,
        "physical_guard_permitted_export_kw": permitted,
        "physical_guard_status": physical_guard.get("status"),
        "final_control_desired_battery_export_kw": desired,
        "final_control_commands_permitted": getattr(
            control, "commands_permitted", False
        ),
        "observed_grid_export_kw": observed,
        "observed_grid_import_kw": imported,
        "physical_soc_percent": _finite(getattr(snapshot, "battery_soc", None)),
        "desired_work_mode": getattr(control, "desired_work_mode", None),
        "control_blocked_reason": getattr(control, "blocked_reason", None),
        "interpretation": (
            "A single FoxESS grid CT reading cannot prove the requested "
            "battery export was delivered or not delivered: distinguish "
            "ramp time, solar output, household load and protective veto. "
            "Use sustained matched intervals or cumulative supplier meter "
            "evidence before changing dispatch or earnings."
        ),
    }


def reward_settlement_evidence(audit: Mapping[str, Any]) -> dict[str, Any]:
    """Separate ROI-included estimates from supplier-confirmed receipts."""
    settled = audit.get("supplier_settlement_available") is True
    return {
        "status": "supplier_verified" if settled else "estimates_awaiting_supplier",
        "roi_included_estimate_pence": _finite(
            audit.get("included_estimate_pence", audit.get("included_total_pence"))
        ),
        "roi_included_total_pence": _finite(audit.get("included_total_pence")),
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
            "normal Agile export is not an additional Power Down bonus. "
            "Matched awarded Octopoints are recorded separately at their "
            "£1 per 800 points equivalent; award does not prove cash redemption."
        ),
        "reporting_only": True,
    }
