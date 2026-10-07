"""Alpha9.69 physical cheap-target parity against the Alpha9.68 forecast rule."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from kems_core import SimulationConfig, SimulationEngine, SimulationState, Snapshot

UK = ZoneInfo("Europe/London")
WHEN = datetime(2026, 9, 27, 14, 0, tzinfo=UK)


def _snapshot(**changes):
    values = dict(
        timestamp=WHEN,
        off_peak=True,
        intelligent_slot=True,
        ev_connected=True,
        ev_charging=True,
        ev_power_kw=6.0,
        ev_load_in_house_load=True,
        house_load_kw=8.0,
        solar_power_kw=0.0,
        battery_soc=45.0,
        next_offpeak_start=WHEN + timedelta(hours=9, minutes=30),
        offpeak_end=WHEN + timedelta(hours=1),
    )
    values.update(changes)
    return Snapshot(**values)


def _config():
    return SimulationConfig(
        battery_capacity_kwh=30.0,
        battery_reserve_percent=10.0,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        proposal_solar_enabled=False,
        export_tariff_status="awaiting",
        site_import_limit_kw=14.5,
    )


def test_live_forecast_retains_old_learned_profile_not_ev_excluded_twin():
    engine = SimulationEngine()
    snap = _snapshot()
    records = [_snapshot(timestamp=WHEN - timedelta(minutes=10 * i)) for i in (2, 1, 0)]
    config = _config()
    twin = engine._empty_current_state(
        snap, records, config, forecast_energy_until_offpeak_kwh=12.0
    )
    live = engine.legacy_no_export_control_view(snap, records, config, 12.0, twin)
    assert twin.no_export_mode_active is True
    assert twin.home_reserve_forecast_source == "recent_non_ev_average"
    assert live.home_reserve_forecast_source == "learned_profile"
    # Old rule: 12 kWh learned load less 1 h of 8 kW active cheap load.
    # Forecast safety factor is 1.10, then account for battery efficiency.
    target = 3.0 + (12.0 - 8.0) * 1.10 / config.discharge_efficiency
    assert live.overnight_charge_target_percent == pytest.approx(
        round(target / 30.0 * 100.0, 1)
    )
    assert live.current_simulated_grid_bypass_power_kw == 8.0
    assert live.overnight_charge_target_percent != twin.overnight_charge_target_percent
    assert live.no_export_mode_active is True


def test_legacy_control_view_does_not_edit_daytime_or_paid_export():
    engine = SimulationEngine()
    config = _config()
    snap = _snapshot(off_peak=False, intelligent_slot=False)
    original = SimulationState(no_export_mode_active=True)
    assert (
        engine.legacy_no_export_control_view(snap, [snap], config, 12.0, original)
        is original
    )
    paid = SimulationState(no_export_mode_active=False)
    assert (
        engine.legacy_no_export_control_view(
            _snapshot(), [_snapshot()], config, 12.0, paid
        )
        is paid
    )


def test_real_backend_receives_legacy_view_and_separate_twin_is_advisory():
    kems = Path(__file__).parents[1] / "custom_components" / "kems"
    coordinator = (kems / "coordinator.py").read_text(encoding="utf-8")
    assert "self._simulation.legacy_no_export_control_view(" in coordinator
    assert 'if self.settings.control.operating_mode == "control"' in coordinator
    assert "control_simulation," in coordinator
    assert (
        "proposal = self._control.plan(\n"
        "                    snapshot,\n"
        "                    base_simulation,"
    ) in coordinator
    assert (
        "control=control,\n                snapshot=snapshot,\n                technical_ready="
        in coordinator
    )
    assert (
        "control=proposal,\n                snapshot=snapshot,\n                technical_ready="
        not in coordinator
    )
    assert "self._ev_charge_trace.async_record(" in coordinator
