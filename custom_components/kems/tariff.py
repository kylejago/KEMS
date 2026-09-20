"""User-configurable electricity tariff resolution for KEMS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

INTELLIGENT_EV_MIN_POWER_KW = 0.5
INTELLIGENT_RATE_TOLERANCE_PENCE = 0.25


@dataclass(frozen=True, slots=True)
class ScheduledTariffChange:
    """One future tariff fallback that becomes active from a local calendar date."""

    effective_from: date
    day_rate_pence: float
    offpeak_rate_pence: float
    standing_charge_pence: float


@dataclass(frozen=True, slots=True)
class EffectiveTariffRates:
    """Date-resolved tariff fallback values used for live and future resolution."""

    day_rate_pence: float
    offpeak_rate_pence: float
    standing_charge_pence: float
    effective_from: date | None = None
    next_change: ScheduledTariffChange | None = None


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
    scheduled_changes: tuple[ScheduledTariffChange, ...] = ()


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


def effective_tariff_rates(
    settings: TariffSettings,
    when: datetime | date,
) -> EffectiveTariffRates:
    """Return the fallback tariff that applies on a local calendar date."""
    target_date = when.date() if isinstance(when, datetime) else when
    day_rate = max(float(settings.day_rate_pence), 0.0)
    offpeak_rate = max(float(settings.offpeak_rate_pence), 0.0)
    standing_charge = max(float(settings.standing_charge_pence), 0.0)
    active_from: date | None = None
    next_change: ScheduledTariffChange | None = None

    for change in sorted(
        settings.scheduled_changes, key=lambda item: item.effective_from
    ):
        if change.effective_from <= target_date:
            day_rate = max(float(change.day_rate_pence), 0.0)
            offpeak_rate = max(float(change.offpeak_rate_pence), 0.0)
            standing_charge = max(float(change.standing_charge_pence), 0.0)
            active_from = change.effective_from
        elif next_change is None:
            next_change = change

    return EffectiveTariffRates(
        day_rate_pence=day_rate,
        offpeak_rate_pence=offpeak_rate,
        standing_charge_pence=standing_charge,
        effective_from=active_from,
        next_change=next_change,
    )


def _next_fallback_rate(
    settings: TariffSettings,
    now: datetime,
    *,
    schedule_offpeak: bool,
    next_start: datetime,
    active_end: datetime,
    effective: EffectiveTariffRates,
) -> float:
    """Return the next fallback rate across schedule and effective-date boundaries."""
    next_normal_boundary = active_end if schedule_offpeak else next_start
    candidates = [next_normal_boundary]
    if effective.next_change is not None:
        change_at = datetime.combine(
            effective.next_change.effective_from,
            time.min,
            tzinfo=now.tzinfo,
        )
        if change_at > now:
            candidates.append(change_at)

    next_event = min(candidates)
    next_rates = effective_tariff_rates(settings, next_event)
    next_is_offpeak, _, _ = manual_schedule(
        next_event,
        settings.offpeak_start,
        settings.offpeak_end,
    )
    return (
        next_rates.offpeak_rate_pence if next_is_offpeak else next_rates.day_rate_pence
    )


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
    cheap_rate_pence: float,
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
        ev_power_kw is not None and float(ev_power_kw) >= INTELLIGENT_EV_MIN_POWER_KW
    )
    soc_plausible = ev_soc is None or 0.0 <= float(ev_soc) <= 100.0
    price_corroborated = _rate_matches_cheap(
        live_current_import_rate,
        cheap_rate_pence,
    ) or _rate_matches_cheap(
        live_next_import_rate,
        cheap_rate_pence,
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
        # Grid demand is diagnostic-only here: while Self Use is active, the battery
        # can supply most of the EV load and make genuine Intelligent slots look like
        # low-import contradictions. The authoritative slot/window plus Ohme evidence
        # must therefore not be vetoed by current grid demand.
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
        "octopus_demand_corroboration_required": False,
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
    effective = effective_tariff_rates(settings, now)
    schedule_offpeak, manual_next_start, manual_end = manual_schedule(
        now,
        settings.offpeak_start,
        settings.offpeak_end,
    )
    manual_current_rate = (
        effective.offpeak_rate_pence if schedule_offpeak else effective.day_rate_pence
    )
    manual_next_rate = _next_fallback_rate(
        settings,
        now,
        schedule_offpeak=schedule_offpeak,
        next_start=manual_next_start,
        active_end=manual_end,
        effective=effective,
    )

    if settings.mode == "manual":
        return ResolvedTariff(
            current_import_rate=manual_current_rate,
            next_import_rate=manual_next_rate,
            current_export_rate=max(fallback_export_rate, 0.0),
            electricity_standing_charge=effective.standing_charge_pence,
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
                "effective_fallback_day_rate_pence": effective.day_rate_pence,
                "effective_fallback_offpeak_rate_pence": effective.offpeak_rate_pence,
                "effective_fallback_standing_charge_pence": (
                    effective.standing_charge_pence
                ),
                "fallback_effective_from": (
                    effective.effective_from.isoformat()
                    if effective.effective_from is not None
                    else None
                ),
                "next_scheduled_change": (
                    effective.next_change.effective_from.isoformat()
                    if effective.next_change is not None
                    else None
                ),
            },
        )

    extra_slot_confirmed, confirmation, evidence = _intelligent_extra_slot_evidence(
        settings=settings,
        now=now,
        cheap_rate_pence=effective.offpeak_rate_pence,
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

    evidence["effective_fallback_day_rate_pence"] = effective.day_rate_pence
    evidence["effective_fallback_offpeak_rate_pence"] = effective.offpeak_rate_pence
    evidence["effective_fallback_standing_charge_pence"] = (
        effective.standing_charge_pence
    )
    evidence["fallback_effective_from"] = (
        effective.effective_from.isoformat()
        if effective.effective_from is not None
        else None
    )
    evidence["next_scheduled_change"] = (
        effective.next_change.effective_from.isoformat()
        if effective.next_change is not None
        else None
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
            current_import_rate=effective.offpeak_rate_pence,
            next_import_rate=effective.day_rate_pence,
            current_export_rate=(
                live_current_export_rate
                if live_current_export_rate is not None
                else max(fallback_export_rate, 0.0)
            ),
            electricity_standing_charge=(
                live_standing_charge
                if live_standing_charge is not None
                else effective.standing_charge_pence
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
            else effective.standing_charge_pence
        ),
        off_peak=schedule_offpeak,
        intelligent_slot=False,
        next_offpeak_start=manual_next_start,
        offpeak_end=manual_end,
        source="automatic" if used_live else "manual_fallback",
        intelligent_slot_confirmation=confirmation,
        intelligent_slot_evidence=evidence,
    )
