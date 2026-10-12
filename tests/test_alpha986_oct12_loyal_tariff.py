"""Alpha9.86 Intelligent Octopus Go Loyal Fixed October 12 tariff regressions."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from const import DEFAULT_OPTIONS
from tariff import (
    ScheduledTariffChange,
    TariffSettings,
    effective_tariff_rates,
    resolve_tariff,
)

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
LONDON = ZoneInfo("Europe/London")


def _settings() -> TariffSettings:
    return TariffSettings(
        mode="automatic",
        day_rate_pence=28.3036,
        offpeak_rate_pence=3.4933,
        standing_charge_pence=53.70435,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
        intelligent_slots_enabled=True,
        scheduled_changes=(
            ScheduledTariffChange(
                date(2026, 10, 1), 26.9558095238, 3.326952381, 51.147
            ),
            ScheduledTariffChange(date(2026, 10, 4), 37.17, 8.0, 55.52),
            ScheduledTariffChange(date(2026, 10, 12), 35.88, 6.60, 55.52),
        ),
    )


def test_original_tariff_history_is_preserved() -> None:
    s = _settings()
    before = effective_tariff_rates(s, date(2026, 10, 11))
    after = effective_tariff_rates(s, date(2026, 10, 12))
    assert (before.day_rate_pence, before.offpeak_rate_pence) == (37.17, 8.0)
    assert before.next_change is not None
    assert before.next_change.effective_from == date(2026, 10, 12)
    assert (after.day_rate_pence, after.offpeak_rate_pence) == (35.88, 6.60)
    assert after.standing_charge_pence == 55.52
    assert after.effective_from == date(2026, 10, 12)


def test_new_defaults_preserve_earlier_dates() -> None:
    assert DEFAULT_OPTIONS["tariff_change_2_effective_date"] == "2026-10-04"
    assert DEFAULT_OPTIONS["tariff_change_2_day_rate_pence"] == 37.17
    assert DEFAULT_OPTIONS["tariff_change_3_effective_date"] == "2026-10-12"
    assert DEFAULT_OPTIONS["tariff_change_3_day_rate_pence"] == 35.88
    assert DEFAULT_OPTIONS["tariff_change_3_offpeak_rate_pence"] == 6.60
    assert DEFAULT_OPTIONS["tariff_change_3_standing_charge_pence"] == 55.52

    settings_source = (ROOT / "settings.py").read_text(encoding="utf-8")
    flow_source = (ROOT / "config_flow.py").read_text(encoding="utf-8")
    assert "CONF_TARIFF_CHANGE_3_DATE," in settings_source
    assert "vol.Optional(CONF_TARIFF_CHANGE_3_DATE): DateSelector()" in flow_source
    assert "CONF_TARIFF_CHANGE_3_DATE," in flow_source


def _resolved(current_rate: float, next_rate: float):
    now = datetime(2026, 10, 12, 14, 15, tzinfo=LONDON)
    return resolve_tariff(
        settings=_settings(),
        now=now,
        live_current_import_rate=current_rate,
        live_next_import_rate=next_rate,
        live_current_export_rate=None,
        live_standing_charge=55.52,
        live_off_peak=False,
        live_intelligent_slot=True,
        live_next_offpeak_start=datetime(2026, 10, 12, 14, 0, tzinfo=LONDON),
        live_offpeak_end=datetime(2026, 10, 12, 14, 30, tzinfo=LONDON),
        ev_connected=True,
        ev_charging=True,
        ev_power_kw=7.1,
        ev_soc=55.0,
        fallback_export_rate=0.0,
    )


def test_new_cheap_rate_confirms_corrobated_intelligent_extra_slot() -> None:
    result = _resolved(35.88, 6.60)
    assert result.source == "automatic_intelligent_extra"
    assert result.intelligent_slot is True
    assert result.current_import_rate == 6.60
    assert result.intelligent_slot_evidence["octopus_price_corroborated"] is True


def test_old_cheap_rate_does_not_authorise_new_intelligent_extra_slot() -> None:
    result = _resolved(37.17, 8.0)
    assert result.source == "automatic"
    assert result.intelligent_slot is False
    assert result.intelligent_slot_evidence["octopus_price_corroborated"] is False
    assert result.intelligent_slot_evidence["large_import_permitted"] is False


def test_automatic_mode_continues_to_prefer_live_octopus_prices() -> None:
    result = resolve_tariff(
        settings=_settings(),
        now=datetime(2026, 10, 12, 18, 0, tzinfo=LONDON),
        live_current_import_rate=35.88,
        live_next_import_rate=6.60,
        live_current_export_rate=None,
        live_standing_charge=55.52,
        live_off_peak=False,
        live_intelligent_slot=False,
        live_next_offpeak_start=None,
        live_offpeak_end=None,
        ev_connected=False,
        ev_charging=False,
        ev_power_kw=0.0,
        fallback_export_rate=0.0,
    )
    assert result.source == "automatic"
    assert result.current_import_rate == 35.88
    assert result.next_import_rate == 6.60
    assert result.electricity_standing_charge == 55.52
