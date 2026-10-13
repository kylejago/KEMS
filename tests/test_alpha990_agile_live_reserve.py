"""Alpha9.90 physical house budget must veto simulated-SOC-only export."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from kems_core import ControlConfig, ControlState, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import guard_paid_agile_physical_export

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


def _control() -> ControlState:
    return ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_price_optimised",
        desired_work_mode="Feed-in First",
        desired_battery_to_home_power_kw=1.2,
        desired_battery_export_power_kw=6.4,
        desired_total_discharge_power_kw=7.6,
        desired_grid_export_allowed=True,
        data_fresh=True,
        plan_safe=True,
    )


def _snapshot(**changes: object) -> Snapshot:
    state = dict(
        timestamp=NOW,
        battery_soc=44.0,
        ev_connected=False,
        ev_charging=False,
        source_data_age_seconds=10.0,
        next_offpeak_start=NOW + timedelta(hours=12),
    )
    state.update(changes)
    return Snapshot(**state)


def _forecast(**changes: object) -> SimpleNamespace:
    state = dict(
        ready=True,
        expected_house_remaining_today_kwh=16.974,
        expected_solar_remaining_today_kwh=19.09,
        confidence_percent=60.0,
    )
    state.update(changes)
    return SimpleNamespace(**state)


def _guard(snapshot=None, forecast=None, control=None):
    return guard_paid_agile_physical_export(
        control or _control(),
        snapshot or _snapshot(),
        forecast or _forecast(),
        SimulationConfig(),
        ControlConfig(stale_data_seconds=180),
        now=NOW,
    )


def test_real_44_soc_blocks_export_despite_high_simulated_agile_soc() -> None:
    actual, report = _guard()
    assert actual.desired_work_mode == "Self Use"
    assert actual.desired_battery_export_power_kw == 0.0
    assert actual.desired_battery_to_home_power_kw == 1.2
    assert report["physical_soc_percent"] == 44.0
    assert report["exportable_physical_energy_kwh"] == 0.0


def test_replans_using_actual_soc_and_house_forecast() -> None:
    high, high_report = _guard(snapshot=_snapshot(battery_soc=100.0))
    assert high.desired_battery_export_power_kw == 6.4
    assert high_report["status"] == "permitted_with_physical_house_budget"
    low, low_report = _guard(
        snapshot=_snapshot(battery_soc=65.0),
        forecast=_forecast(expected_house_remaining_today_kwh=24.0),
    )
    assert low.desired_battery_export_power_kw == 0.0
    assert low_report["status"] == "blocked"


def test_small_remaining_surplus_caps_physical_kw() -> None:
    actual, report = _guard(
        snapshot=_snapshot(battery_soc=60.0),
        forecast=_forecast(expected_house_remaining_today_kwh=20.0),
    )
    assert 0.0 < actual.desired_battery_export_power_kw < 6.4
    assert report["status"] == "capped"
    assert actual.desired_total_discharge_power_kw == round(
        1.2 + actual.desired_battery_export_power_kw, 3
    )


def test_missing_stale_forecast_or_deadline_fails_closed() -> None:
    examples = (
        (_snapshot(battery_soc=None), _forecast()),
        (_snapshot(source_data_age_seconds=300), _forecast()),
        (_snapshot(stale_fields=("battery_soc",)), _forecast()),
        (_snapshot(next_offpeak_start=None), _forecast()),
        (_snapshot(next_offpeak_start=NOW - timedelta(minutes=1)), _forecast()),
        (_snapshot(), _forecast(ready=False)),
        (_snapshot(), _forecast(expected_house_remaining_today_kwh=None)),
    )
    for snapshot, forecast in examples:
        result, report = _guard(snapshot=snapshot, forecast=forecast)
        assert result.desired_battery_export_power_kw == 0.0, report
        assert report["status"] == "blocked"


def test_weak_solar_confidence_never_reduces_house_reserve() -> None:
    _, report = _guard()
    assert report["conservative_solar_credit_kwh"] == 0.0
    _, confident = _guard(forecast=_forecast(confidence_percent=95.0))
    assert confident["conservative_solar_credit_kwh"] > 0.0


def test_ev_connected_or_unknown_blocks_paid_export() -> None:
    for connected in (True, None):
        control, report = _guard(snapshot=_snapshot(ev_connected=connected))
        assert control.desired_battery_export_power_kw == 0.0
        assert "EV connected/uncertain" in report["reason"]


def test_no_export_plan_and_confirmed_cheap_unchanged() -> None:
    from dataclasses import replace

    current = _control()
    idle = replace(current, desired_battery_export_power_kw=0.0)
    same, _ = _guard(control=idle)
    assert same is idle
    cheap = _snapshot(off_peak=True)
    untouched, report = _guard(snapshot=cheap)
    assert untouched is not None
    assert report["status"] == "higher_priority_cheap_or_event"


def test_paid_ev_hold_gate_is_invoked_before_physical_backend() -> None:
    from pathlib import Path

    root = Path(__file__).parents[1] / "custom_components" / "kems"
    coordinator = (root / "coordinator.py").read_text(encoding="utf-8")
    backend = (root / "foxess_control_backend.py").read_text(encoding="utf-8")
    source = coordinator.split("control = apply_happy_hour_control(", 1)[1]
    assert source.index("guard_paid_agile_physical_export(") < source.index(
        "self._ev_grid_hold.async_apply("
    )
    assert source.index("self._ev_grid_hold.async_apply(") < source.index(
        "self._foxess_control.async_update("
    )
    assert "paid_agile_ev_hold_eligible=paid_agile_ev_hold_eligible" in coordinator
    assert "paid_agile_ev_hold_eligible" in backend
