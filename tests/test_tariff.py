"""Tests for editable automatic/manual electricity tariffs."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from tariff import (
    ScheduledTariffChange,
    TariffSettings,
    effective_tariff_rates,
    manual_schedule,
    resolve_tariff,
)

LONDON = ZoneInfo("Europe/London")
SETTINGS = TariffSettings(
    mode="manual",
    day_rate_pence=28.3,
    offpeak_rate_pence=3.5,
    standing_charge_pence=53.7,
    offpeak_start=time(23, 30),
    offpeak_end=time(5, 30),
    intelligent_slots_enabled=True,
)


def test_manual_schedule_supports_period_across_midnight() -> None:
    """The normal overnight cheap period must work on both sides of midnight."""
    late = datetime(2026, 8, 6, 23, 45, tzinfo=LONDON)
    early = datetime(2026, 8, 7, 4, 0, tzinfo=LONDON)
    day = datetime(2026, 8, 7, 12, 0, tzinfo=LONDON)

    assert manual_schedule(late, time(23, 30), time(5, 30))[0] is True
    assert manual_schedule(early, time(23, 30), time(5, 30))[0] is True
    is_offpeak, next_start, active_end = manual_schedule(day, time(23, 30), time(5, 30))
    assert is_offpeak is False
    assert next_start.hour == 23 and next_start.minute == 30
    assert active_end.hour == 5 and active_end.minute == 30
    assert active_end.date().isoformat() == "2026-08-08"


def test_manual_tariff_uses_editable_day_and_offpeak_prices() -> None:
    """Manual mode must ignore live prices and follow the user's schedule."""
    result = resolve_tariff(
        settings=SETTINGS,
        now=datetime(2026, 8, 6, 12, 0, tzinfo=LONDON),
        live_current_import_rate=99.0,
        live_next_import_rate=98.0,
        live_current_export_rate=20.0,
        live_standing_charge=100.0,
        live_off_peak=True,
        live_intelligent_slot=False,
        live_next_offpeak_start=None,
        live_offpeak_end=None,
        ev_charging=False,
        fallback_export_rate=12.0,
    )

    assert result.source == "manual"
    assert result.current_import_rate == 28.3
    assert result.next_import_rate == 3.5
    assert result.electricity_standing_charge == 53.7
    assert result.current_export_rate == 12.0
    assert result.off_peak is False


def test_automatic_tariff_prefers_live_values_and_falls_back_safely() -> None:
    """Automatic mode should keep live prices but use the configured schedule."""
    automatic = TariffSettings(
        mode="automatic",
        day_rate_pence=30.0,
        offpeak_rate_pence=5.0,
        standing_charge_pence=60.0,
        offpeak_start=time(23, 0),
        offpeak_end=time(6, 0),
        intelligent_slots_enabled=True,
    )
    result = resolve_tariff(
        settings=automatic,
        now=datetime(2026, 8, 6, 12, 0, tzinfo=LONDON),
        live_current_import_rate=27.5,
        live_next_import_rate=None,
        live_current_export_rate=None,
        live_standing_charge=52.0,
        live_off_peak=False,
        live_intelligent_slot=False,
        live_next_offpeak_start=None,
        live_offpeak_end=None,
        ev_charging=False,
        fallback_export_rate=15.0,
    )

    assert result.source == "automatic"
    assert result.current_import_rate == 27.5
    assert result.next_import_rate == 5.0
    assert result.electricity_standing_charge == 52.0
    assert result.current_export_rate == 15.0
    assert result.off_peak is False


def test_intelligent_slot_cannot_unlock_daytime_cheap_control() -> None:
    """Legacy Intelligent/EV signals must never create a daytime cheap window."""
    result = resolve_tariff(
        settings=SETTINGS,
        now=datetime(2026, 8, 6, 15, 0, tzinfo=LONDON),
        live_current_import_rate=None,
        live_next_import_rate=None,
        live_current_export_rate=None,
        live_standing_charge=None,
        live_off_peak=True,
        live_intelligent_slot=True,
        live_next_offpeak_start=datetime(2026, 8, 6, 15, 0, tzinfo=LONDON),
        live_offpeak_end=datetime(2026, 8, 6, 16, 0, tzinfo=LONDON),
        ev_charging=True,
        fallback_export_rate=12.0,
    )

    assert result.current_import_rate == 28.3
    assert result.off_peak is False
    assert result.intelligent_slot is False
    assert result.next_offpeak_start.hour == 23
    assert result.next_offpeak_start.minute == 30


def test_automatic_live_extra_slot_cannot_move_overnight_deadline() -> None:
    """Live Octopus off-peak timestamps cannot replace the configured window."""
    automatic = TariffSettings(
        mode="automatic",
        day_rate_pence=28.3,
        offpeak_rate_pence=3.5,
        standing_charge_pence=53.7,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
        intelligent_slots_enabled=True,
    )
    now = datetime(2026, 8, 10, 15, 0, tzinfo=LONDON)
    result = resolve_tariff(
        settings=automatic,
        now=now,
        live_current_import_rate=3.5,
        live_next_import_rate=28.3,
        live_current_export_rate=None,
        live_standing_charge=53.7,
        live_off_peak=True,
        live_intelligent_slot=True,
        live_next_offpeak_start=datetime(2026, 8, 10, 15, 0, tzinfo=LONDON),
        live_offpeak_end=datetime(2026, 8, 10, 16, 0, tzinfo=LONDON),
        ev_charging=True,
        fallback_export_rate=12.0,
    )

    assert result.current_import_rate == 3.5
    assert result.off_peak is False
    assert result.intelligent_slot is False
    assert result.next_offpeak_start == datetime(2026, 8, 10, 23, 30, tzinfo=LONDON)
    assert result.offpeak_end == datetime(2026, 8, 11, 5, 30, tzinfo=LONDON)


def test_automatic_tariff_replaces_past_live_next_start_during_active_window() -> None:
    """The configured next overnight window stays authoritative while cheap."""
    automatic = TariffSettings(
        mode="automatic",
        day_rate_pence=28.3,
        offpeak_rate_pence=3.5,
        standing_charge_pence=53.7,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
        intelligent_slots_enabled=True,
    )
    now = datetime(2026, 8, 10, 23, 45, tzinfo=LONDON)
    result = resolve_tariff(
        settings=automatic,
        now=now,
        live_current_import_rate=3.5,
        live_next_import_rate=28.3,
        live_current_export_rate=None,
        live_standing_charge=53.7,
        live_off_peak=True,
        live_intelligent_slot=False,
        live_next_offpeak_start=datetime(2026, 8, 10, 23, 30, tzinfo=LONDON),
        live_offpeak_end=datetime(2026, 8, 11, 5, 30, tzinfo=LONDON),
        ev_charging=False,
        fallback_export_rate=12.0,
    )

    assert result.off_peak is True
    assert result.next_offpeak_start == datetime(2026, 8, 11, 23, 30, tzinfo=LONDON)


def _renewal_settings(*, mode: str = "automatic") -> TariffSettings:
    """Return the staged Sep/Oct 2026 tariff used by Alpha9.68."""
    return TariffSettings(
        mode=mode,
        day_rate_pence=28.3036,
        offpeak_rate_pence=3.4933,
        standing_charge_pence=53.70435,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
        intelligent_slots_enabled=True,
        scheduled_changes=(
            ScheduledTariffChange(
                effective_from=date(2026, 10, 1),
                day_rate_pence=26.9558095238,
                offpeak_rate_pence=3.326952381,
                standing_charge_pence=51.147,
            ),
            ScheduledTariffChange(
                effective_from=date(2026, 10, 4),
                day_rate_pence=37.17,
                offpeak_rate_pence=8.0,
                standing_charge_pence=55.52,
            ),
        ),
    )


def test_scheduled_tariff_does_not_change_rates_before_effective_date() -> None:
    """Staged renewal data must not alter September fallback rates."""
    rates = effective_tariff_rates(
        _renewal_settings(),
        datetime(2026, 9, 30, 12, 0, tzinfo=LONDON),
    )

    assert rates.day_rate_pence == 28.3036
    assert rates.offpeak_rate_pence == 3.4933
    assert rates.standing_charge_pence == 53.70435
    assert rates.effective_from is None
    assert rates.next_change is not None
    assert rates.next_change.effective_from == date(2026, 10, 1)


def test_vat_only_tariff_change_applies_from_first_october() -> None:
    """The current tariff loses 5% VAT from 1 Oct without applying renewal yet."""
    rates = effective_tariff_rates(
        _renewal_settings(),
        datetime(2026, 10, 1, 0, 0, tzinfo=LONDON),
    )

    assert rates.day_rate_pence == 26.9558095238
    assert rates.offpeak_rate_pence == 3.326952381
    assert rates.standing_charge_pence == 51.147
    assert rates.effective_from == date(2026, 10, 1)
    assert rates.next_change is not None
    assert rates.next_change.effective_from == date(2026, 10, 4)


def test_renewed_tariff_applies_from_fourth_october() -> None:
    """The quoted renewal becomes the active fallback from 4 Oct."""
    rates = effective_tariff_rates(
        _renewal_settings(),
        datetime(2026, 10, 4, 0, 0, tzinfo=LONDON),
    )

    assert rates.day_rate_pence == 37.17
    assert rates.offpeak_rate_pence == 8.0
    assert rates.standing_charge_pence == 55.52
    assert rates.effective_from == date(2026, 10, 4)
    assert rates.next_change is None


def test_automatic_live_values_remain_authoritative_after_renewal() -> None:
    """Scheduled values are fallbacks and never override available Octopus data."""
    result = resolve_tariff(
        settings=_renewal_settings(),
        now=datetime(2026, 10, 4, 12, 0, tzinfo=LONDON),
        live_current_import_rate=37.19,
        live_next_import_rate=8.01,
        live_current_export_rate=None,
        live_standing_charge=55.54,
        live_off_peak=False,
        live_intelligent_slot=False,
        live_next_offpeak_start=None,
        live_offpeak_end=None,
        ev_charging=False,
        fallback_export_rate=0.0,
    )

    assert result.source == "automatic"
    assert result.current_import_rate == 37.19
    assert result.next_import_rate == 8.01
    assert result.electricity_standing_charge == 55.54
    assert (
        result.intelligent_slot_evidence["effective_fallback_day_rate_pence"]
        == 37.17
    )
    assert (
        result.intelligent_slot_evidence["effective_fallback_offpeak_rate_pence"]
        == 8.0
    )
    assert result.intelligent_slot_evidence["fallback_effective_from"] == "2026-10-04"


def test_automatic_fallback_uses_renewed_rates_when_live_values_are_missing() -> None:
    """Missing live prices after 4 Oct fall back to the renewed tariff."""
    result = resolve_tariff(
        settings=_renewal_settings(),
        now=datetime(2026, 10, 4, 12, 0, tzinfo=LONDON),
        live_current_import_rate=None,
        live_next_import_rate=None,
        live_current_export_rate=None,
        live_standing_charge=None,
        live_off_peak=False,
        live_intelligent_slot=False,
        live_next_offpeak_start=None,
        live_offpeak_end=None,
        ev_charging=False,
        fallback_export_rate=0.0,
    )

    assert result.source == "manual_fallback"
    assert result.current_import_rate == 37.17
    assert result.next_import_rate == 8.0
    assert result.electricity_standing_charge == 55.52


def test_intelligent_extra_slot_uses_effective_renewed_cheap_rate() -> None:
    """Post-renewal extra slots must corroborate against 8p rather than 3.4933p."""
    now = datetime(2026, 10, 4, 10, 30, tzinfo=LONDON)
    result = resolve_tariff(
        settings=_renewal_settings(),
        now=now,
        live_current_import_rate=37.17,
        live_next_import_rate=8.0,
        live_current_export_rate=None,
        live_standing_charge=55.52,
        live_off_peak=False,
        live_intelligent_slot=True,
        live_next_offpeak_start=datetime(2026, 10, 4, 10, 0, tzinfo=LONDON),
        live_offpeak_end=datetime(2026, 10, 4, 11, 0, tzinfo=LONDON),
        ev_charging=True,
        fallback_export_rate=0.0,
        ev_connected=True,
        ev_power_kw=3.0,
        ev_soc=70.0,
        live_current_demand_kw=5.0,
    )

    assert result.source == "automatic_intelligent_extra"
    assert result.intelligent_slot is True
    assert result.current_import_rate == 8.0
    assert result.next_import_rate == 37.17
    assert result.intelligent_slot_confirmation == "confirmed"
    assert result.intelligent_slot_evidence["octopus_price_corroborated"] is True
    assert (
        result.intelligent_slot_evidence["effective_fallback_offpeak_rate_pence"]
        == 8.0
    )
