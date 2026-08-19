"""Tests for editable automatic/manual electricity tariffs."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from tariff import TariffSettings, manual_schedule, resolve_tariff

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
