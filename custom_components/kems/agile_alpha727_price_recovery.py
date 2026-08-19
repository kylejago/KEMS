"""Alpha 7.27 Agile price-horizon observability and recovery evidence.

Alpha7.26 introduced exact-slot retries for missing Agile prices, but its evidence
was only published as Home Assistant entity attributes. KEMS diagnostics therefore
could not prove whether the retry ran, whether Octopus returned no price, or whether
KEMS failed to retrieve it.

Alpha7.27 makes that evidence part of the Agile runtime state itself. It also adds a
small context-window retry when an exact half-hour request does not recover the
missing slot. Only a rate whose validity exactly matches the missing settlement
period may be added, so unresolved prices are never invented.

This remains simulation/shadow only. It never permits FoxESS hardware writes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from aiohttp import ClientError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import agile_alpha726_provisional as alpha726
from . import agile_smart_export as agile
from . import agile_smart_export_runtime_base as runtime
from .agile_price_horizon import expected_slots_for_day, missing_slots_for_day

MAX_TARGETED_RATE_RETRIES = 4
CONTEXT_PADDING = timedelta(minutes=30)


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


def _rate_slots(rates: list[agile.AgileRate]) -> list[dict[str, str]]:
    """Return the compact slot shape used by the horizon helper."""
    return [
        {
            "valid_from": item.valid_from.isoformat(),
            "valid_to": item.valid_to.isoformat(),
        }
        for item in rates
    ]


def _result_interval(item: dict[str, Any]) -> dict[str, Any]:
    """Return a safe interval summary for diagnostic evidence."""
    start = _parse_utc(item.get("valid_from"))
    end = _parse_utc(item.get("valid_to"))
    return {
        "valid_from_utc": start.isoformat() if start else None,
        "valid_to_utc": end.isoformat() if end else None,
        "valid_from_local": (
            start.astimezone(agile.LONDON).isoformat() if start else None
        ),
        "valid_to_local": end.astimezone(agile.LONDON).isoformat() if end else None,
        "value_inc_vat": item.get("value_inc_vat"),
    }


def _matching_results(
    results: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    """Return only results that exactly match the missing settlement slot."""
    return [
        item
        for item in results
        if _parse_utc(item.get("valid_from")) == start
        and _parse_utc(item.get("valid_to")) == end
    ]


async def _request_window(
    self,
    *,
    start: datetime,
    end: datetime,
    request_kind: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch one bounded Octopus rate window and return observable evidence."""
    evidence: dict[str, Any] = {
        "kind": request_kind,
        "period_from_utc": start.astimezone(UTC).isoformat(),
        "period_to_utc": end.astimezone(UTC).isoformat(),
        "period_from_local": start.astimezone(agile.LONDON).isoformat(),
        "period_to_local": end.astimezone(agile.LONDON).isoformat(),
        "http_status": None,
        "result_count": 0,
        "returned_intervals": [],
        "error_type": None,
        "error": None,
    }
    if not self._rate_url:
        evidence["error_type"] = "tariff_discovery_incomplete"
        evidence["error"] = "Agile rate URL is unavailable"
        return [], evidence

    session = async_get_clientsession(self._hass)
    params = {
        "period_from": agile._api_dt(start),
        "period_to": agile._api_dt(end),
        "page_size": 20,
    }
    try:
        async with session.get(
            self._rate_url,
            params=params,
            timeout=15,
        ) as response:
            evidence["http_status"] = response.status
            response.raise_for_status()
            data = await response.json()
    except (ClientError, TimeoutError, TypeError, ValueError) as err:
        evidence["error_type"] = type(err).__name__
        evidence["error"] = str(err)
        return [], evidence

    results = [item for item in data.get("results", []) if isinstance(item, dict)]
    evidence["result_count"] = len(results)
    evidence["returned_intervals"] = [_result_interval(item) for item in results[:8]]
    return results, evidence


def _agile_rate_from_result(self, item: dict[str, Any]) -> agile.AgileRate:
    """Convert one verified target result into the KEMS Agile rate model."""
    return agile.AgileRate.from_dict(
        {
            "product_code": self._product_code,
            "tariff_code": self._tariff_code,
            "value_inc_vat": item["value_inc_vat"],
            "valid_from": item["valid_from"],
            "valid_to": item["valid_to"],
        }
    )


def _overall_outcome(
    *,
    future_missing: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> str:
    """Classify the recovery result without guessing at upstream state."""
    if not future_missing:
        return "no_future_missing_slots"
    if any(item.get("outcome") == "retrieval_error" for item in attempts):
        return "retrieval_error"
    if not unresolved:
        return "recovered"
    if any(item.get("outcome") == "recovered_context" for item in attempts):
        return "partially_recovered"
    if all(
        item.get("outcome") in {"octopus_slot_not_published", "octopus_no_results"}
        for item in attempts
    ):
        return "octopus_missing_price"
    return "unresolved"


async def _fetch_rates_with_observable_recovery(
    self,
    records,
    now: datetime,
) -> None:
    """Refresh rates, recover exact missing slots, and retain full evidence."""
    local_day = now.astimezone(agile.LONDON).date()
    expected = expected_slots_for_day(local_day, agile.LONDON)
    diagnostics: dict[str, Any] = {
        "version": "0.7.0-alpha7.27",
        "generated_at": now.isoformat(),
        "local_date": local_day.isoformat(),
        "expected_slots": len(expected),
        "primary_fetch_status": "pending",
        "primary_fetch_error_type": None,
        "primary_fetch_error": None,
        "known_after_primary_fetch": None,
        "primary_missing_labels": [],
        "targeted_retry_attempted": False,
        "targeted_retry_slots": [],
        "targeted_retry_recovered": [],
        "targeted_retry_attempt_count": 0,
        "attempts": [],
        "known_after_targeted_retry": None,
        "unresolved_missing_labels": [],
        "recovery_outcome": "pending",
    }

    try:
        await alpha726.alpha726_original_fetch_rates(self, records, now)
    except (ClientError, TimeoutError, KeyError, TypeError, ValueError) as err:
        diagnostics["primary_fetch_status"] = "error"
        diagnostics["primary_fetch_error_type"] = type(err).__name__
        diagnostics["primary_fetch_error"] = str(err)
        diagnostics["recovery_outcome"] = "primary_fetch_error"
        self._kems_alpha727_price_fetch_diagnostics = diagnostics
        self._kems_alpha726_rate_fetch_diagnostics = diagnostics
        raise

    diagnostics["primary_fetch_status"] = "success"
    missing_before = missing_slots_for_day(
        _rate_slots(self._rates),
        local_day,
        agile.LONDON,
    )
    diagnostics["known_after_primary_fetch"] = len(expected) - len(missing_before)
    diagnostics["primary_missing_labels"] = [
        str(item.get("label") or "unknown") for item in missing_before
    ]

    now_utc = now.astimezone(UTC)
    future_missing = [
        item
        for item in missing_before
        if (_parse_utc(item.get("valid_to")) or now_utc) > now_utc
    ][:MAX_TARGETED_RATE_RETRIES]
    diagnostics["targeted_retry_attempted"] = bool(future_missing)
    diagnostics["targeted_retry_slots"] = [
        str(item.get("label") or "unknown") for item in future_missing
    ]

    recovered_rates: list[agile.AgileRate] = []
    attempts: list[dict[str, Any]] = []
    for slot in future_missing:
        start = _parse_utc(slot.get("valid_from"))
        end = _parse_utc(slot.get("valid_to"))
        attempt: dict[str, Any] = {
            "label": (
                str(item_label) if (item_label := slot.get("label")) else "unknown"
            ),
            "timezone": slot.get("timezone"),
            "target_valid_from_utc": start.isoformat() if start else None,
            "target_valid_to_utc": end.isoformat() if end else None,
            "target_valid_from_local": (
                start.astimezone(agile.LONDON).isoformat() if start else None
            ),
            "target_valid_to_local": (
                end.astimezone(agile.LONDON).isoformat() if end else None
            ),
            "exact_request": None,
            "context_request": None,
            "matched_result_count": 0,
            "outcome": "unresolved",
        }
        if start is None or end is None:
            attempt["outcome"] = "retrieval_error"
            attempt["error_type"] = "invalid_slot_boundary"
            attempts.append(attempt)
            continue

        exact_results, exact_evidence = await _request_window(
            self,
            start=start,
            end=end,
            request_kind="exact_half_hour",
        )
        exact_matches = _matching_results(exact_results, start, end)
        exact_evidence["matching_result_count"] = len(exact_matches)
        attempt["exact_request"] = exact_evidence

        if exact_evidence.get("error_type"):
            attempt["outcome"] = "retrieval_error"
            attempts.append(attempt)
            continue

        matches = exact_matches
        if matches:
            attempt["matched_result_count"] = len(matches)
            attempt["outcome"] = "recovered_exact"
        else:
            context_results, context_evidence = await _request_window(
                self,
                start=start - CONTEXT_PADDING,
                end=end + CONTEXT_PADDING,
                request_kind="context_window",
            )
            context_matches = _matching_results(context_results, start, end)
            context_evidence["matching_result_count"] = len(context_matches)
            attempt["context_request"] = context_evidence

            if context_evidence.get("error_type"):
                attempt["outcome"] = "retrieval_error"
                attempts.append(attempt)
                continue
            if context_matches:
                matches = context_matches
                attempt["matched_result_count"] = len(context_matches)
                attempt["outcome"] = "recovered_context"
            elif context_results:
                attempt["outcome"] = "octopus_slot_not_published"
            else:
                attempt["outcome"] = "octopus_no_results"

        for item in matches:
            try:
                recovered_rates.append(_agile_rate_from_result(self, item))
            except (KeyError, TypeError, ValueError) as err:
                attempt["outcome"] = "retrieval_error"
                attempt["error_type"] = type(err).__name__
                attempt["error"] = str(err)
        attempts.append(attempt)

    if recovered_rates:
        self._rates = agile._dedupe([*self._rates, *recovered_rates])
        self._dirty = True

    missing_after = missing_slots_for_day(
        _rate_slots(self._rates),
        local_day,
        agile.LONDON,
    )
    unresolved_labels = [str(item.get("label") or "unknown") for item in missing_after]
    recovered_labels = [
        str(item.get("label") or "unknown")
        for item in future_missing
        if str(item.get("label") or "unknown") not in unresolved_labels
    ]
    diagnostics["attempts"] = attempts
    diagnostics["targeted_retry_attempt_count"] = len(attempts)
    diagnostics["targeted_retry_recovered"] = recovered_labels
    diagnostics["known_after_targeted_retry"] = len(expected) - len(missing_after)
    diagnostics["unresolved_missing_labels"] = unresolved_labels
    diagnostics["recovery_outcome"] = _overall_outcome(
        future_missing=future_missing,
        attempts=attempts,
        unresolved=missing_after,
    )
    diagnostics["interpretation"] = {
        "recovered_exact": "Exact half-hour request returned the missing price.",
        "recovered_context": (
            "Exact request missed the slot but a wider context request returned it."
        ),
        "octopus_missing_price": (
            "Octopus responded successfully but did not publish the target slot."
        ),
        "retrieval_error": "KEMS could not complete one or more recovery requests.",
    }.get(diagnostics["recovery_outcome"], diagnostics["recovery_outcome"])

    self._kems_alpha727_price_fetch_diagnostics = diagnostics
    self._kems_alpha726_rate_fetch_diagnostics = diagnostics


def _publish_with_alpha727(self, state: dict[str, Any]) -> None:
    """Embed price-recovery evidence in Agile state and refresh the HA sensor."""
    diagnostics = getattr(self, "_kems_alpha727_price_fetch_diagnostics", {})
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    if diagnostics:
        state["price_fetch_diagnostics"] = diagnostics
        state["price_fetch_status"] = diagnostics.get("recovery_outcome")

    alpha727_original_publish(self, state)

    if not diagnostics:
        return
    known = diagnostics.get("known_after_targeted_retry")
    expected = diagnostics.get("expected_slots")
    outcome = diagnostics.get("recovery_outcome") or "unknown"
    self._set(
        "sensor.kems_agile_price_fetch_diagnostics",
        f"{known}/{expected} slots · {outcome}",
        {
            "friendly_name": "Agile price fetch diagnostics",
            "mode": "simulation_only",
            **diagnostics,
            "hardware_writes": "blocked",
        },
    )


def install_alpha727_price_recovery_patch() -> None:
    """Install observable, context-aware Agile missing-price recovery."""
    global alpha727_original_publish

    current_fetch = runtime.EfficientAgileSmartExportManager._fetch_rates
    if not getattr(current_fetch, "_kems_alpha727_price_recovery", False):
        _fetch_rates_with_observable_recovery._kems_alpha727_price_recovery = True
        runtime.EfficientAgileSmartExportManager._fetch_rates = (
            _fetch_rates_with_observable_recovery
        )

    current_publish = runtime.EfficientAgileSmartExportManager._publish
    if not getattr(current_publish, "_kems_alpha727_price_recovery", False):
        alpha727_original_publish = current_publish
        _publish_with_alpha727._kems_alpha727_price_recovery = True
        runtime.EfficientAgileSmartExportManager._publish = _publish_with_alpha727
