"""Alpha 7.41 progressive Agile planning while prices are still publishing.

KEMS already has two conservative incomplete-horizon layers:

* Alpha7.26 keeps a provisional economic plan and reserves the full discharge
  capacity of unknown settlement periods.
* Alpha7.28 allows known-price dispatch only when the current price is known,
  unknown-slot capacity is fully reserved, and the missing prices have been
  proven to be an upstream Octopus gap.

Alpha7.41 recognises the normal publication phase as another bounded upstream
state. A successful broad Octopus fetch that simply does not contain every
future settlement period is sufficient publication evidence provided there is
no retrieval error. Known-price slots may therefore continue through the
existing Alpha7.28 bounded planner while the unpublished slots remain unknown
and fully reserved. No price is guessed or filled in.

Tomorrow's price set is also published as a first-class progressive plan so the
UI can say "46/48 published" rather than "unavailable". It is rebuilt whenever
the Agile manager refreshes; when the final prices arrive the state naturally
becomes complete.

The current settlement period must still have a real price before deliberate
battery export is permitted. Alpha7.34 latest-safe-start, Alpha7.40 economic
opportunity protection, the 10% reserve, inverter/export limits, shadow safety,
and the hard FoxESS write block remain unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from . import agile_alpha728_bounded_partial as alpha728
from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from .agile_price_horizon import missing_slots_for_day

_TOMORROW_SENSOR = "sensor.kems_agile_tomorrow_publication_plan"


def _parse_utc(value: Any) -> datetime | None:
    """Parse an ISO timestamp and normalise it to UTC."""
    if value in (None, ""):
        return None
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _publication_recovery_evidence(
    self,
    horizon: dict[str, Any],
) -> dict[str, Any]:
    """Accept a clean publication gap without weakening retrieval-error holds."""
    result = alpha741_original_recovery_evidence(self, horizon)
    if result.get("verified"):
        result["publication_pending"] = False
        return result

    diagnostics = getattr(self, "_kems_alpha727_price_fetch_diagnostics", None)
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    missing_labels = {
        str(item)
        for item in (horizon.get("missing_labels") or [])
        if str(item).strip()
    }
    primary_missing = {
        str(item)
        for item in (diagnostics.get("primary_missing_labels") or [])
        if str(item).strip()
    }
    unresolved = {
        str(item)
        for item in (diagnostics.get("unresolved_missing_labels") or [])
        if str(item).strip()
    }
    attempts = [
        item for item in diagnostics.get("attempts", []) if isinstance(item, dict)
    ]
    relevant_attempts = {
        str(item.get("label")): str(item.get("outcome") or "")
        for item in attempts
        if str(item.get("label")) in missing_labels
    }
    retrieval_error = any(
        outcome == "retrieval_error" for outcome in relevant_attempts.values()
    )
    labels_accounted_for = bool(
        missing_labels and missing_labels.issubset(primary_missing | unresolved)
    )
    clean_publication_gap = bool(
        diagnostics.get("primary_fetch_status") == "success"
        and labels_accounted_for
        and not retrieval_error
    )

    if not clean_publication_gap:
        result["publication_pending"] = False
        return result

    return {
        **result,
        "verified": True,
        "publication_pending": True,
        "reason": (
            "Octopus broad price fetch succeeded but future settlement prices are "
            "still publishing; known-price dispatch may use the bounded partial "
            "planner while unknown-slot capacity remains fully reserved"
        ),
        "recovery_outcome": diagnostics.get("recovery_outcome"),
        "missing_labels": sorted(missing_labels),
        "unresolved_labels": sorted(unresolved),
        "relevant_attempt_outcomes": relevant_attempts,
        "publication_policy": "known prices only; never invent unpublished rates",
    }


def _missing_capacity_kwh(
    missing: list[dict[str, Any]],
    *,
    max_kw: float,
) -> float:
    """Return full AC discharge opportunity represented by missing price slots."""
    capacity = 0.0
    for slot in missing:
        if not isinstance(slot, dict):
            continue
        start = _parse_utc(slot.get("valid_from"))
        end = _parse_utc(slot.get("valid_to"))
        if start is None or end is None or end <= start:
            continue
        capacity += max(max_kw, 0.0) * (end - start).total_seconds() / 3600.0
    return round(max(capacity, 0.0), 3)


def _progressive_tomorrow_state(self, state: dict[str, Any]) -> dict[str, Any]:
    """Describe tomorrow using every published price without guessing the rest."""
    generated = _parse_utc(state.get("generated_at"))
    if generated is None:
        return {
            "available": False,
            "status": "Waiting for generated timestamp",
            "mode": "progressive_known_prices",
        }

    local_now = generated.astimezone(agile.LONDON)
    tomorrow = local_now.date() + timedelta(days=1)
    slots = state.get("tomorrow_slots")
    slots = slots if isinstance(slots, list) else []
    missing = missing_slots_for_day(slots, tomorrow, agile.LONDON)
    quality = state.get("price_quality")
    quality = quality if isinstance(quality, dict) else {}
    expected = int(quality.get("tomorrow_expected") or (len(slots) + len(missing)))
    known = len(slots)
    complete = bool(expected > 0 and known == expected and not missing)

    config = getattr(self, "_panel_config", None)
    if config is not None:
        max_kw = min(
            max(float(config.max_discharge_kw), 0.0),
            max(float(config.inverter_limit_kw), 0.0),
            max(float(config.export_limit_kw), 0.0),
        )
    else:
        max_kw = 0.0
    unknown_capacity = _missing_capacity_kwh(missing, max_kw=max_kw)
    missing_labels = [
        str(item.get("label") or item.get("local_from") or "unknown")
        for item in missing
        if isinstance(item, dict)
    ]

    if complete:
        status = f"Complete — {known}/{expected} prices"
        mode = "complete_price_horizon"
    elif known:
        status = f"Provisional — using {known}/{expected} published prices"
        mode = "progressive_known_prices"
    else:
        status = "Waiting for Octopus publication"
        mode = "waiting_for_publication"

    periods = state.get("periods")
    periods = periods if isinstance(periods, dict) else {}
    tomorrow_period = periods.get("tomorrow")
    tomorrow_period = tomorrow_period if isinstance(tomorrow_period, dict) else {}
    provisional_comparison = tomorrow_period.get("comparison")
    if not isinstance(provisional_comparison, dict):
        provisional_comparison = None

    return {
        "available": bool(known),
        "status": status,
        "mode": mode,
        "complete": complete,
        "provisional": bool(known and not complete),
        "known_price_count": known,
        "expected_price_count": expected,
        "missing_price_count": len(missing),
        "missing_price_labels": missing_labels,
        "missing_price_slots": missing,
        "unknown_slot_capacity_reserved_kwh": unknown_capacity,
        "maximum_export_power_kw": round(max_kw, 3),
        "current_slot_policy": "no deliberate export without a real current price",
        "unknown_price_policy": "reserve full slot capacity; never guess price",
        "replan_policy": "rebuild automatically as new Octopus prices arrive",
        "provisional_comparison": provisional_comparison,
        "hardware_writes": "blocked",
        "real_backend_available": False,
    }


def _annotate_progressive_state(self, state: dict[str, Any]) -> dict[str, Any]:
    """Attach progressive publication evidence to Agile state and tomorrow period."""
    progressive = _progressive_tomorrow_state(self, state)
    state["tomorrow_publication_plan"] = progressive

    quality = state.get("price_quality")
    if isinstance(quality, dict):
        quality["tomorrow_progressive_planning"] = bool(progressive.get("available"))
        quality["tomorrow_planning_mode"] = progressive.get("mode")
        quality["tomorrow_missing_labels"] = progressive.get("missing_price_labels", [])
        quality["tomorrow_unknown_capacity_reserved_kwh"] = progressive.get(
            "unknown_slot_capacity_reserved_kwh"
        )
        if progressive.get("provisional"):
            quality["tomorrow_status"] = str(progressive.get("status"))

    periods = state.get("periods")
    if isinstance(periods, dict):
        tomorrow = periods.get("tomorrow")
        if isinstance(tomorrow, dict):
            tomorrow["publication_complete"] = bool(progressive.get("complete"))
            tomorrow["provisional"] = bool(progressive.get("provisional"))
            tomorrow["provisional_price_ready"] = bool(progressive.get("available"))
            tomorrow["published_price_count"] = progressive.get("known_price_count")
            tomorrow["expected_price_count"] = progressive.get("expected_price_count")
            tomorrow["missing_price_labels"] = progressive.get(
                "missing_price_labels", []
            )
            tomorrow["unknown_slot_capacity_reserved_kwh"] = progressive.get(
                "unknown_slot_capacity_reserved_kwh"
            )
            tomorrow["publication_status"] = progressive.get("status")
            tomorrow["replan_policy"] = progressive.get("replan_policy")

    horizon = state.get("planning_horizon")
    if isinstance(horizon, dict) and not horizon.get("complete"):
        horizon["progressive_publication_policy"] = (
            "use known-price slots only when bounded partial safety passes; reserve "
            "full unknown-slot capacity"
        )
        horizon["unknown_prices_are_never_invented"] = True
    return progressive


def _publish_with_alpha741(self, state: dict[str, Any]) -> None:
    """Publish progressive price availability before the normal Alpha7.40 chain."""
    progressive = _annotate_progressive_state(self, state)
    alpha741_original_publish(self, state)
    self._set(
        _TOMORROW_SENSOR,
        progressive.get("status") or "Unavailable",
        {
            "friendly_name": "Agile tomorrow progressive publication plan",
            **progressive,
        },
    )


def install_alpha741_partial_publication_patch() -> None:
    """Install progressive publication planning after the Alpha7.40 optimiser."""
    global alpha741_original_publish
    global alpha741_original_recovery_evidence

    recovery = alpha728._recovery_evidence
    if not getattr(recovery, "_kems_alpha741_partial_publication", False):
        alpha741_original_recovery_evidence = recovery
        _publication_recovery_evidence._kems_alpha741_partial_publication = True
        alpha728._recovery_evidence = _publication_recovery_evidence

    publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(publish, "_kems_alpha741_partial_publication", False):
        alpha741_original_publish = publish
        _publish_with_alpha741._kems_alpha741_partial_publication = True
        runtime.EfficientAgileSmartExportManager._publish = _publish_with_alpha741
