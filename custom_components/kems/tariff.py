"""User-configurable electricity tariff resolution for KEMS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True, slots=True)
class TariffSettings:
    """Validated tariff settings used to resolve each live snapshot."""

    mode: str
    day_rate_pence: float
    offpeak_rate_pence: float
    standing_charge_pence: float
    offpeak_start: time
    offpeak_end: time
    intelligent_slots_enabled: bool


@dataclass(frozen=True, slots=True)
class ResolvedTariff:
    """Resolved tariff observation after applying live/manual preferences."""

    current_import_rate: float | None
    next_import_rate: float | None
    current_export_rate: float | None
    electricity_standing_charge: float | None
    off_peak: bool | None
    intelligent_slot: bool | None
    next_offpeak_start: datetime | None
    offpeak_end: datetime | None
    source: str


def parse_time(value: object, default: time) -> time:
    """Parse a Home Assistant time-selector value."""
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    if isinstance(value, str):
        text = value.strip()
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(text, fmt).time()
            except ValueError:
                continue
    return default


def manual_schedule(
    now: datetime,
    start: time,
    end: time,
) -> tuple[bool, datetime, datetime]:
    """Return off-peak state plus the next start and relevant end."""
    local_now = now
    current_time = local_now.timetz().replace(tzinfo=None)
    spans_midnight = start >= end

    if spans_midnight:
        is_offpeak = current_time >= start or current_time < end
    else:
        is_offpeak = start <= current_time < end

    start_today = local_now.replace(
        hour=start.hour,
        minute=start.minute,
        second=start.second,
        microsecond=0,
    )
    end_today = local_now.replace(
        hour=end.hour,
        minute=end.minute,
        second=end.second,
        microsecond=0,
    )

    if is_offpeak:
        if spans_midnight and current_time >= start:
            active_end = end_today + timedelta(days=1)
        else:
            active_end = end_today
        next_start = start_today + timedelta(days=1)
    else:
        next_start = (
            start_today if start_today > local_now else start_today + timedelta(days=1)
        )
        active_end = next_start.replace(
            hour=end.hour,
            minute=end.minute,
            second=end.second,
        )
        if spans_midnight:
            active_end += timedelta(days=1)

    return is_offpeak, next_start, active_end


def resolve_tariff(
    *,
    settings: TariffSettings,
    now: datetime,
    live_current_import_rate: float | None,
    live_next_import_rate: float | None,
    live_current_export_rate: float | None,
    live_standing_charge: float | None,
    live_off_peak: bool | None,
    live_intelligent_slot: bool | None,
    live_next_offpeak_start: datetime | None,
    live_offpeak_end: datetime | None,
    ev_charging: bool | None,
    fallback_export_rate: float,
) -> ResolvedTariff:
    """Resolve live tariff data with user-controlled manual fallback/override."""
    schedule_offpeak, manual_next_start, manual_end = manual_schedule(
        now,
        settings.offpeak_start,
        settings.offpeak_end,
    )
    intelligent_slot = (
        live_intelligent_slot if settings.intelligent_slots_enabled else False
    )
    extra_slot_confirmed = intelligent_slot is True and ev_charging is True
    manual_offpeak = schedule_offpeak or extra_slot_confirmed
    manual_current_rate = (
        settings.offpeak_rate_pence if manual_offpeak else settings.day_rate_pence
    )
    manual_next_rate = (
        settings.day_rate_pence if manual_offpeak else settings.offpeak_rate_pence
    )

    if settings.mode == "manual":
        return ResolvedTariff(
            current_import_rate=manual_current_rate,
            next_import_rate=manual_next_rate,
            current_export_rate=max(fallback_export_rate, 0.0),
            electricity_standing_charge=settings.standing_charge_pence,
            off_peak=manual_offpeak,
            intelligent_slot=intelligent_slot,
            next_offpeak_start=manual_next_start,
            offpeak_end=manual_end,
            source="manual",
        )

    used_live = any(
        value is not None
        for value in (
            live_current_import_rate,
            live_next_import_rate,
            live_standing_charge,
            live_off_peak,
            live_next_offpeak_start,
            live_offpeak_end,
        )
    )
    return ResolvedTariff(
        current_import_rate=(
            live_current_import_rate
            if live_current_import_rate is not None
            else manual_current_rate
        ),
        next_import_rate=(
            live_next_import_rate
            if live_next_import_rate is not None
            else manual_next_rate
        ),
        current_export_rate=(
            live_current_export_rate
            if live_current_export_rate is not None
            else max(fallback_export_rate, 0.0)
        ),
        electricity_standing_charge=(
            live_standing_charge
            if live_standing_charge is not None
            else settings.standing_charge_pence
        ),
        off_peak=(live_off_peak if live_off_peak is not None else manual_offpeak),
        intelligent_slot=intelligent_slot,
        next_offpeak_start=(
            live_next_offpeak_start
            if live_next_offpeak_start is not None and live_next_offpeak_start > now
            else manual_next_start
        ),
        offpeak_end=live_offpeak_end or manual_end,
        source="automatic" if used_live else "manual_fallback",
    )
