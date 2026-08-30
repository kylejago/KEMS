"""Alpha8.58 regressions for fail-closed Intelligent cheap-slot confirmation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from custom_components.kems.agile_smart_export import AgileRate, AgileSmartExportManager
from custom_components.kems.kems_core import (
    SimulationConfig,
    SimulationEngine,
    Snapshot,
)
from custom_components.kems.tariff import TariffSettings, resolve_tariff

LONDON = ZoneInfo("Europe/London")


def _settings(*, enabled: bool = True) -> TariffSettings:
    return TariffSettings(
        mode="automatic",
        day_rate_pence=28.3036,
        offpeak_rate_pence=3.4933,
        standing_charge_pence=53.70435,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
        intelligent_slots_enabled=enabled,
    )


def _field_resolution(**overrides):
    values = {
        "settings": _settings(),
        "now": datetime(2026, 8, 30, 17, 51, tzinfo=LONDON),
        "live_current_import_rate": 28.3036,
        "live_next_import_rate": 3.4933,
        "live_current_export_rate": 12.0,
        "live_standing_charge": 53.70435,
        "live_off_peak": False,
        "live_intelligent_slot": True,
        "live_next_offpeak_start": datetime(2026, 8, 30, 16, 33, tzinfo=UTC),
        "live_offpeak_end": datetime(2026, 8, 30, 17, 0, tzinfo=UTC),
        "ev_charging": True,
        "fallback_export_rate": 12.0,
        "ev_connected": True,
        "ev_power_kw": 7.326,
        "ev_soc": 56.0,
        "live_current_demand_kw": 8.682,
    }
    values.update(overrides)
    return resolve_tariff(**values)


def test_field_intelligent_slot_is_confirmed_from_octopus_and_ohme() -> None:
    """30 Aug field evidence must permit the genuine daytime cheap dispatch."""
    resolved = _field_resolution()

    assert resolved.source == "automatic_intelligent_extra"
    assert resolved.intelligent_slot is True
    assert resolved.off_peak is False
    assert resolved.current_import_rate == 3.4933
    assert resolved.next_import_rate == 28.3036
    assert resolved.offpeak_end == datetime(2026, 8, 30, 17, 0, tzinfo=UTC)
    assert resolved.intelligent_slot_evidence["large_import_permitted"] is True
    assert resolved.intelligent_slot_evidence["octopus_price_corroborated"] is True
    assert resolved.intelligent_slot_evidence["octopus_demand_corroborated"] is True
    assert resolved.intelligent_slot_evidence["ohme_power_active"] is True

    snapshot = Snapshot(
        off_peak=resolved.off_peak,
        intelligent_slot=resolved.intelligent_slot,
        ev_charging=True,
    )
    assert snapshot.cheap_period_confirmed is True


def test_extra_slot_fails_closed_when_any_primary_confirmation_is_missing() -> None:
    """No single stale/partial integration signal may authorise large import."""
    cases = (
        {"settings": _settings(enabled=False)},
        {"live_intelligent_slot": False},
        {"live_next_offpeak_start": None},
        {"live_offpeak_end": None},
        {"ev_connected": False},
        {"ev_charging": False},
        {"ev_power_kw": 0.0},
        {"ev_soc": 156.0},
        {"live_current_import_rate": 28.3036, "live_next_import_rate": 28.3036},
        {"live_current_demand_kw": 0.0},
    )
    for override in cases:
        resolved = _field_resolution(**override)
        assert resolved.intelligent_slot is False
        assert resolved.intelligent_slot_evidence["large_import_permitted"] is False


def test_regular_overnight_window_does_not_require_ev_confirmation() -> None:
    """The contractual 23:30-05:30 cheap window remains independently authoritative."""
    resolved = resolve_tariff(
        settings=_settings(),
        now=datetime(2026, 8, 30, 23, 45, tzinfo=LONDON),
        live_current_import_rate=3.4933,
        live_next_import_rate=28.3036,
        live_current_export_rate=12.0,
        live_standing_charge=53.70435,
        live_off_peak=True,
        live_intelligent_slot=False,
        live_next_offpeak_start=None,
        live_offpeak_end=None,
        ev_charging=False,
        fallback_export_rate=12.0,
        ev_connected=False,
        ev_power_kw=0.0,
        ev_soc=56.0,
        live_current_demand_kw=0.8,
    )
    assert resolved.off_peak is True
    assert resolved.intelligent_slot is False
    snapshot = Snapshot(
        off_peak=resolved.off_peak,
        intelligent_slot=resolved.intelligent_slot,
        ev_charging=False,
    )
    assert snapshot.cheap_period_confirmed is True


def _cheap_records() -> list[Snapshot]:
    start = datetime(2026, 8, 30, 17, 30, tzinfo=LONDON)
    return [
        Snapshot(
            timestamp=start,
            current_import_rate=3.4933,
            off_peak=False,
            intelligent_slot=True,
            ev_connected=True,
            ev_charging=True,
            ev_power_kw=7.0,
            house_load_kw=1.0,
            solar_power_kw=2.0,
            battery_soc=50.0,
        ),
        Snapshot(
            timestamp=start + timedelta(minutes=30),
            current_import_rate=28.3036,
            off_peak=False,
            intelligent_slot=False,
            ev_connected=True,
            ev_charging=False,
            ev_power_kw=0.0,
            house_load_kw=1.0,
            solar_power_kw=2.0,
            battery_soc=50.0,
        ),
    ]


def test_full_kems_cheap_slot_routes_solar_to_battery_before_grid_charge() -> None:
    """PV must displace Grid battery charging during a confirmed cheap slot."""
    config = SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=10.0,
        battery_initial_percent=50.0,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        export_tariff_status="active",
        export_rate_pence=12.0,
        proposal_solar_enabled=False,
    )
    records = _cheap_records()
    result = SimulationEngine().simulate_today(
        records,
        records[-1].timestamp,
        config,
        current_snapshot=records[-1],
    )

    assert float(result.simulated_solar_to_battery_kwh or 0.0) > 0.9
    assert float(result.simulated_grid_to_battery_kwh or 0.0) > 2.0
    assert float(result.simulated_solar_export_kwh or 0.0) == 0.0
    assert float(result.simulated_grid_import_kwh or 0.0) >= 3.0


def test_agile_replay_cheap_slot_prioritises_solar_charge() -> None:
    """Positive Outgoing price must not beat cheap-slot battery refill priority."""
    records = _cheap_records()
    config = SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=10.0,
        battery_initial_percent=50.0,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        export_tariff_status="active",
        export_rate_pence=12.0,
        proposal_solar_enabled=False,
    )
    rate = AgileRate(
        product_code="test",
        tariff_code="test",
        value_inc_vat=22.88,
        valid_from=records[0].timestamp.astimezone(UTC),
        valid_to=records[1].timestamp.astimezone(UTC),
    )

    manager = object.__new__(AgileSmartExportManager)
    manager._simulation = SimulationEngine()
    summary, plan = manager._agile_day(
        records,
        [rate],
        config,
        _settings(),
        50.0,
    )

    assert summary["ready"] is True
    assert summary["solar_to_battery_kwh"] > 0.9
    assert summary["solar_export_kwh"] == 0.0
    assert summary["grid_import_kwh"] >= 3.0
    assert plan[0]["solar_to_battery_kwh"] > 0.9
    assert "store solar" in plan[0]["actions"]


def test_solar_only_exports_after_battery_charge_headroom_is_exhausted() -> None:
    """Battery-full/charge-limited PV may still export; remainder is not curtailed."""
    records = _cheap_records()
    records[0] = replace(records[0], battery_soc=99.9, solar_power_kw=6.0)
    config = SimulationConfig(
        battery_capacity_kwh=56.42,
        battery_reserve_percent=10.0,
        battery_initial_percent=99.9,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        export_tariff_status="active",
        export_rate_pence=12.0,
        proposal_solar_enabled=False,
    )
    result = SimulationEngine().simulate_today(
        records,
        records[-1].timestamp,
        config,
        current_snapshot=records[-1],
    )
    assert float(result.simulated_solar_to_battery_kwh or 0.0) > 0.0
    assert float(result.simulated_solar_export_kwh or 0.0) > 0.0
