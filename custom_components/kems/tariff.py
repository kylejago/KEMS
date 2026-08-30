"""User-configurable electricity tariff resolution for KEMS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

INTELLIGENT_EV_MIN_POWER_KW = 0.5
INTELLIGENT_RATE_TOLERANCE_PENCE = 0.25


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
    intelligent_slot_confirmation: str = "not_evaluated"
    intelligent_slot_evidence: dict[str, Any] = field(default_factory=dict)


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


def _rate_matches_cheap(value: float | None, cheap_rate: float) -> bool:
    """Return whether a live rate corroborates the configured cheap rate."""
    if value is None:
        return False
    tolerance = max(
        INTELLIGENT_RATE_TOLERANCE_PENCE,
        abs(cheap_rate) * 0.10,
    )
    return abs(float(value) - cheap_rate) <= tolerance


def _window_active(
    now: datetime,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    """Return whether both Intelligent boundaries contain the current instant."""
    if start is None or end is None:
        return False
    if start.tzinfo is None:
        start = start.replace(tzinfo=now.tzinfo)
    if end.tzinfo is None:
        end = end.replace(tzinfo=now.tzinfo)
    return start <= now < end


def _intelligent_extra_slot_evidence(
    *,
    settings: TariffSettings,
    now: datetime,
    live_current_import_rate: float | None,
    live_next_import_rate: float | None,
    live_off_peak: bool | None,
    live_intelligent_slot: bool | None,
    live_next_offpeak_start: datetime | None,
    live_offpeak_end: datetime | None,
    live_current_demand_kw: float | None,
    ev_connected: bool | None,
    ev_charging: bool | None,
    ev_power_kw: float | None,
    ev_soc: float | None,
) -> tuple[bool, str, dict[str, Any]]:
    """Require corroborated Octopus + Ohme evidence before large extra-slot import."""
    slot_enabled = settings.intelligent_slots_enabled
    slot_signal = live_intelligent_slot is True
    window_complete = (
        live_next_offpeak_start is not None and live_offpeak_end is not None
    )
    window_active = _window_active(
        now,
        live_next_offpeak_start,
        live_offpeak_end,
    )
    power_active = (
        ev_power_kw is not None
        and float(ev_power_kw) >= INTELLIGENT_EV_MIN_POWER_KW
    )
    soc_plausible = ev_soc is None or 0.0 <= float(ev_soc) <= 100.0
    price_corroborated = _rate_matches_cheap(
        live_current_import_rate,
        settings.offpeak_rate_pence,
    ) or _rate_matches_cheap(
        live_next_import_rate,
        settings.offpeak_rate_pence,
    )

    demand_corroborated = True
    minimum_expected_demand_kw: float | None = None
    if live_current_demand_kw is not None and ev_power_kw is not None:
        minimum_expected_demand_kw = max(float(ev_power_kw) * 0.5, 0.5)
        demand_corroborated = (
            float(live_current_demand_kw) + 0.05 >= minimum_expected_demand_kw
        )

    checks = (
        ("disabled", slot_enabled),
        ("intelligent slot is not ON", slot_signal),
        ("Intelligent start/end window is unavailable", window_complete),
        ("current time is outside the Intelligent window", window_active),
        ("Ohme does not confirm the EV is connected", ev_connected is True),
        ("Ohme does not confirm active charging", ev_charging is True),
        ("Ohme charging power is below confirmation threshold", power_active),
        ("Ohme vehicle SOC is implausible", soc_plausible),
        ("Octopus price data does not corroborate the cheap rate", price_corroborated),
        ("Octopus current demand contradicts Ohme charging power", demand_corroborated),
    )
    confirmed = all(passed for _, passed in checks)
    reason = "confirmed"
    if not confirmed:
        reason = next(label for label, passed in checks if not passed)

    evidence: dict[str, Any] = {
        "enabled": slot_enabled,
        "confirmed": confirmed,
        "reason": reason,
        "octopus_intelligent_slot": live_intelligent_slot,
        "octopus_intelligent_window_start": (
            live_next_offpeak_start.isoformat()
            if live_next_offpeak_start is not None
            else None
        ),
        "octopus_intelligent_window_end": (
            live_offpeak_end.isoformat() if live_offpeak_end is not None else None
        ),
        "octopus_intelligent_window_active": window_active,
        "octopus_off_peak": live_off_peak,
        "octopus_current_rate_pence": live_current_import_rate,
        "octopus_next_rate_pence": live_next_import_rate,
        "octopus_price_corroborated": price_corroborated,
        "octopus_current_demand_kw": live_current_demand_kw,
        "octopus_demand_corroborated": demand_corroborated,
        "minimum_expected_demand_kw": minimum_expected_demand_kw,
        "ohme_connected": ev_connected,
        "ohme_charging": ev_charging,
        "ohme_power_kw": ev_power_kw,
        "ohme_power_active": power_active,
        "ohme_soc_percent": ev_soc,
        "ohme_soc_plausible": soc_plausible,
        "large_import_permitted": confirmed,
    }
    return confirmed, reason, evidence


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
    ev_connected: bool | None = None,
    ev_power_kw: float | None = None,
    ev_soc: float | None = None,
    live_current_demand_kw: float | None = None,
) -> ResolvedTariff:
    """Resolve normal overnight cheap periods plus fail-closed Intelligent extras."""
    schedule_offpeak, manual_next_start, manual_end = manual_schedule(
        now,
        settings.offpeak_start,
        settings.offpeak_end,
    )
    manual_current_rate = (
        settings.offpeak_rate_pence if schedule_offpeak else settings.day_rate_pence
    )
    manual_next_rate = (
        settings.day_rate_pence if schedule_offpeak else settings.offpeak_rate_pence
    )

    if settings.mode == "manual":
        return ResolvedTariff(
            current_import_rate=manual_current_rate,
            next_import_rate=manual_next_rate,
            current_export_rate=max(fallback_export_rate, 0.0),
            electricity_standing_charge=settings.standing_charge_pence,
            off_peak=schedule_offpeak,
            intelligent_slot=False,
            next_offpeak_start=manual_next_start,
            offpeak_end=manual_end,
            source="manual",
            intelligent_slot_confirmation="manual tariff mode",
            intelligent_slot_evidence={
                "enabled": settings.intelligent_slots_enabled,
                "confirmed": False,
                "reason": "manual tariff mode",
                "large_import_permitted": schedule_offpeak,
            },
        )

    extra_slot_confirmed, confirmation, evidence = (
        _intelligent_extra_slot_evidence(
            settings=settings,
            now=now,
            live_current_import_rate=live_current_import_rate,
            live_next_import_rate=live_next_import_rate,
            live_off_peak=live_off_peak,
            live_intelligent_slot=live_intelligent_slot,
            live_next_offpeak_start=live_next_offpeak_start,
            live_offpeak_end=live_offpeak_end,
            live_current_demand_kw=live_current_demand_kw,
            ev_connected=ev_connected,
            ev_charging=ev_charging,
            ev_power_kw=ev_power_kw,
            ev_soc=ev_soc,
        )
    )

    used_live = any(
        value is not None
        for value in (
            live_current_import_rate,
            live_next_import_rate,
            live_current_export_rate,
            live_standing_charge,
        )
    )
    if extra_slot_confirmed and not schedule_offpeak:
        return ResolvedTariff(
            current_import_rate=settings.offpeak_rate_pence,
            next_import_rate=settings.day_rate_pence,
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
            off_peak=False,
            intelligent_slot=True,
            next_offpeak_start=manual_next_start,
            offpeak_end=live_offpeak_end,
            source="automatic_intelligent_extra",
            intelligent_slot_confirmation=confirmation,
            intelligent_slot_evidence=evidence,
        )

    evidence["large_import_permitted"] = schedule_offpeak
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
        off_peak=schedule_offpeak,
        intelligent_slot=False,
        next_offpeak_start=manual_next_start,
        offpeak_end=manual_end,
        source="automatic" if used_live else "manual_fallback",
        intelligent_slot_confirmation=confirmation,
        intelligent_slot_evidence=evidence,
    )
