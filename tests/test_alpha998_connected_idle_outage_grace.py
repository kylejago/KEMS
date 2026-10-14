"""Alpha9.98: bounded plugged-in idle continuity while cloud Ohme is unavailable.

The EV shares the site bus: this is not independent circuit isolation. A fresh
FoxESS load baseline mitigates (but cannot eliminate) undetected EV draw.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from kems_core import ControlConfig, ControlState, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import (
    PaidAgileConnectedIdleContinuity,
    guard_paid_agile_physical_export,
)

NOW = datetime(2026, 10, 14, 20, 5, 20, tzinfo=UTC)


def snapshot(at: datetime = NOW, **changes: object) -> Snapshot:
    data = dict(
        timestamp=at,
        battery_soc=75.0,
        battery_power_kw=6.45,
        source_data_age_seconds=5.0,
        source_age_seconds={
            "battery_soc": 2.0,
            "battery_power_kw": 2.0,
            "house_load_kw": 5.0,
            "grid_import_kw": 5.0,
        },
        next_offpeak_start=at + timedelta(hours=2),
        house_load_kw=1.069,
        grid_import_kw=0.0,
        ev_connected=True,
        ev_charging=False,
        ev_power_kw=0.0,
        ev_power_age_seconds=29.3,
    )
    data.update(changes)
    return Snapshot(**data)


def control() -> ControlState:
    return ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_price_optimised",
        desired_work_mode="Feed-in First",
        desired_battery_export_power_kw=5.0,
        desired_battery_to_home_power_kw=1.0,
        desired_total_discharge_power_kw=6.0,
        desired_grid_export_allowed=True,
        data_fresh=True,
        plan_safe=True,
    )


def physical_guard(
    snap: Snapshot,
    continuity: PaidAgileConnectedIdleContinuity | None,
    *,
    at: datetime,
    permission: bool = True,
    evidence: str = "bounded_connected_idle_source_grace",
) -> tuple[ControlState, dict]:
    return guard_paid_agile_physical_export(
        control(),
        snap,
        SimpleNamespace(
            ready=True,
            expected_house_remaining_today_kwh=1.0,
            expected_solar_remaining_today_kwh=0.0,
            confidence_percent=0.0,
        ),
        SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_reserve_percent=15.0,
            discharge_efficiency=0.95,
        ),
        ControlConfig(stale_data_seconds=180),
        now=at,
        ev_export_safe=permission,
        ev_export_evidence=evidence,
        connected_idle_continuity=continuity,
    )


def unavailable(at: datetime, **extra: object) -> Snapshot:
    changes = dict(
        ev_connected=None,
        ev_charging=None,
        ev_power_kw=None,
        ev_power_age_seconds=None,
        house_load_kw=1.09,
    )
    changes.update(extra)
    return snapshot(at, **changes)


def test_evening_40_second_cloud_dropout_keeps_paid_export() -> None:
    proof = PaidAgileConnectedIdleContinuity()
    assert not proof.assess(snapshot(), now=NOW)
    outage_at = NOW + timedelta(seconds=42)
    during = unavailable(outage_at)
    assert proof.assess(during, now=outage_at)
    planned, report = physical_guard(during, proof, at=outage_at)
    assert planned.desired_battery_export_power_kw == 5.0, report
    assert report["status"] == "permitted_with_physical_house_budget"

    still_out = unavailable(outage_at + timedelta(seconds=40))
    assert proof.assess(still_out, now=outage_at + timedelta(seconds=40))
    planned, report = physical_guard(
        still_out, proof, at=outage_at + timedelta(seconds=40)
    )
    assert planned.desired_battery_export_power_kw == 5.0, report


def test_grace_expires_after_60_seconds_without_renewal() -> None:
    proof = PaidAgileConnectedIdleContinuity()
    proof.assess(snapshot(), now=NOW)
    outage_at = NOW + timedelta(seconds=42)
    assert proof.assess(unavailable(outage_at), now=outage_at)
    after = outage_at + timedelta(seconds=61)
    lost = unavailable(after)
    assert not proof.assess(lost, now=after)
    desired, report = physical_guard(lost, proof, at=after)
    assert desired.desired_battery_export_power_kw == 0.0, report
    # Still unavailable: another cycle cannot restart the window.
    later = after + timedelta(seconds=5)
    assert not proof.assess(unavailable(later), now=later)


def test_live_charging_and_positive_power_immediately_veto() -> None:
    for changes in (
        {"ev_connected": True, "ev_charging": True},
        {"ev_power_kw": 1.4},
        {"ev_power_kw": 7.0},
    ):
        proof = PaidAgileConnectedIdleContinuity()
        proof.assess(snapshot(), now=NOW)
        start = NOW + timedelta(seconds=40)
        assert proof.assess(unavailable(start), now=start)
        actual = unavailable(start + timedelta(seconds=2))
        for key, value in changes.items():
            setattr(actual, key, value)
        assert not proof.assess(actual, now=start + timedelta(seconds=2))
        desired, _ = physical_guard(actual, proof, at=start + timedelta(seconds=2))
        assert desired.desired_battery_export_power_kw == 0.0


def test_physical_site_load_spike_aborts_for_remainder_of_outage() -> None:
    proof = PaidAgileConnectedIdleContinuity()
    proof.assess(snapshot(), now=NOW)
    at = NOW + timedelta(seconds=40)
    assert proof.assess(unavailable(at), now=at)
    spike = unavailable(at + timedelta(seconds=5), house_load_kw=7.5)
    assert not proof.assess(spike, now=at + timedelta(seconds=5))
    desired, _ = physical_guard(spike, proof, at=at + timedelta(seconds=5))
    assert desired.desired_battery_export_power_kw == 0.0
    later = at + timedelta(seconds=7)
    assert not proof.assess(unavailable(later), now=later)


def test_grid_import_and_stale_modbus_both_abort_continuity() -> None:
    for changes in (
        {"grid_import_kw": 1.2},
        {"house_load_kw": None},
        {"source_age_seconds": {"house_load_kw": 40.0}},
        {"stale_fields": ("house_load_kw",)},
    ):
        proof = PaidAgileConnectedIdleContinuity()
        proof.assess(snapshot(), now=NOW)
        at = NOW + timedelta(seconds=40)
        lost = unavailable(at)
        for key, value in changes.items():
            setattr(lost, key, value)
        assert not proof.assess(lost, now=at)
        desired, _ = physical_guard(lost, proof, at=at)
        assert desired.desired_battery_export_power_kw == 0.0


def test_no_restart_carryover_or_forged_continuity_flag() -> None:
    at = NOW + timedelta(seconds=40)
    lost = unavailable(at)
    empty = PaidAgileConnectedIdleContinuity()
    assert not empty.assess(lost, now=at)
    assert physical_guard(lost, empty, at=at)[0].desired_battery_export_power_kw == 0.0

    ready = PaidAgileConnectedIdleContinuity()
    ready.assess(snapshot(), now=NOW)
    assert ready.assess(lost, now=at)
    assert physical_guard(lost, None, at=at)[0].desired_battery_export_power_kw == 0.0
    assert physical_guard(
        lost, ready, at=at, permission=False
    )[0].desired_battery_export_power_kw == 0.0
    assert physical_guard(
        lost, ready, at=at, evidence="confirmed_connected_idle_zero_power"
    )[0].desired_battery_export_power_kw == 0.0


def test_fresh_idle_report_is_only_way_to_rearm() -> None:
    proof = PaidAgileConnectedIdleContinuity()
    proof.assess(snapshot(), now=NOW)
    start = NOW + timedelta(seconds=40)
    assert proof.assess(unavailable(start), now=start)
    expired_at = start + timedelta(seconds=61)
    assert not proof.assess(unavailable(expired_at), now=expired_at)
    # A new independently confirmed cloud idle reading rearms the session.
    recovered_at = start + timedelta(seconds=65)
    assert not proof.assess(snapshot(recovered_at), now=recovered_at)
    assert proof.assess(
        unavailable(recovered_at + timedelta(seconds=20)),
        now=recovered_at + timedelta(seconds=20),
    )


def test_unplugged_and_bad_last_idle_report_cannot_seed_connected_grace() -> None:
    for bad in (
        {"ev_connected": False},
        {"ev_charging": True},
        {"ev_power_kw": 0.5},
        {"ev_power_age_seconds": 31.0},
        {"house_load_kw": None},
    ):
        proof = PaidAgileConnectedIdleContinuity()
        snap = snapshot()
        for key, value in bad.items():
            setattr(snap, key, value)
        proof.assess(snap, now=NOW)
        at = NOW + timedelta(seconds=40)
        assert not proof.assess(unavailable(at), now=at)
