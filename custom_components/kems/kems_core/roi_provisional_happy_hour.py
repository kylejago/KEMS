"""Conservative provisional Happy Hour credit from *observed* meter intervals.

A partial hour stays explicitly partial. No missed meter interval is filled
with an invented sample or multiplied out to the full hour. A previous
individually verified adjacent hour can supply an indicative tariff proxy
for legacy samples that predate capture of per-sample tariffs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo

_LONDON = ZoneInfo("Europe/London")
_MAX_SAMPLE_GAP_SECONDS = 180
_MIN_OBSERVED_SECONDS = 600


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) and result >= 0 else None


def _dt(value):
    try:
        value = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo is not None else None


def _reading(sample):
    if isinstance(sample, Mapping):
        at = sample.get("timestamp")
        kw = sample.get("grid_import_kw")
        rate = sample.get("import_rate_pence")
    else:
        at = getattr(sample, "timestamp", None)
        kw = getattr(sample, "grid_import_kw", None)
        rate = getattr(sample, "import_rate_pence", None)
    return _dt(at), _number(kw), _number(rate)


def _adjacent_verified_rate(receipts, start):
    """Accept a past verified receipt ending *exactly* when this hour starts."""
    for item in receipts:
        if not isinstance(item, Mapping) or item.get("completed") is not True:
            continue
        end = _dt(item.get("end"))
        if end is None or end != start:
            continue
        rate = _number(item.get("rate_pence"))
        credit = _number(item.get("credit_pence"))
        if rate is not None and rate <= 200 and credit is not None:
            return rate
    return None


def estimate_partial_reward_hours(
    *,
    windows: Iterable[Mapping],
    readings: Iterable,
    completed_receipts: Iterable[Mapping],
    now: datetime,
) -> list[dict]:
    """Return one bounded, read-only credit *estimate* per incomplete booked hour."""
    receipts = list(completed_receipts)
    completed = {
        (_dt(item.get("start")), _dt(item.get("end")))
        for item in receipts
        if isinstance(item, Mapping) and item.get("completed") is True
    }
    samples = sorted(
        (
            (at, kw, rate)
            for at, kw, rate in map(_reading, readings)
            if at is not None and kw is not None and kw <= 30
        ),
        key=lambda item: item[0],
    )
    results = []
    seen = set()
    for window in windows:
        if not isinstance(window, Mapping) or not (
            window.get("booking_source") == "octopus_joined_events"
            or window.get("event_id")
            or window.get("event_code")
        ):
            continue
        start, end = _dt(window.get("start")), _dt(window.get("end"))
        if (
            start is None
            or end is None
            or not 55 <= (end - start).total_seconds() / 60 <= 65
            or end > now
            or (start, end) in completed
            or (start, end) in seen
        ):
            continue
        seen.add((start, end))
        past = [item for item in samples if start <= item[0] <= end]
        if len(past) < 2:
            continue
        fallback_rate = _adjacent_verified_rate(receipts, start)
        witnessed_kwh = witnessed_pence = seconds = 0.0
        proxy_rate_used = False
        for left, right in zip(past, past[1:]):
            elapsed = (right[0] - left[0]).total_seconds()
            if not 0 < elapsed <= _MAX_SAMPLE_GAP_SECONDS:
                continue
            rate_left, rate_right = left[2], right[2]
            if rate_left is not None and rate_right is not None:
                rate = (rate_left + rate_right) / 2
            elif fallback_rate is not None:
                rate = fallback_rate
                proxy_rate_used = True
            else:
                continue
            if rate > 200:
                continue
            kwh = (left[1] + right[1]) / 2 * elapsed / 3600
            witnessed_kwh += kwh
            witnessed_pence += kwh * rate
            seconds += elapsed
        if seconds < _MIN_OBSERVED_SECONDS or witnessed_kwh <= 0:
            continue
        # Do not assume anything about the unobserved portion or the supplier
        # limit. Stop at the independently confirmed 16 kWh per-hour cap.
        if witnessed_kwh > 16:
            witnessed_pence *= 16 / witnessed_kwh
            witnessed_kwh = 16
        results.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "day": start.astimezone(_LONDON).date().isoformat(),
                "credit_pence": round(witnessed_pence, 6),
                "import_kwh": round(witnessed_kwh, 6),
                "covered_minutes": round(seconds / 60, 1),
                "coverage_percent": round(100 * seconds / (end - start).total_seconds(), 1),
                "rate_basis": (
                    "adjacent_verified_hour_indicative_rate_proxy"
                    if proxy_rate_used else "witnessed_historical_tariff_samples"
                ),
                "basis": "provisional_partial_physical_meter_credit",
                "confidence": "low" if proxy_rate_used else "medium",
                "supplier_settled": False,
                "event_id": window.get("event_id"),
            }
        )
    return results
