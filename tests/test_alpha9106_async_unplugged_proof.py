"""Alpha9.106: asynchronous Ohme status/power reports must not hide explicit unplugged proof."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from kems_core import ControlConfig, ControlState, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import (
    PaidAgileUnpluggedContinuity,
    guard_paid_agile_physical_export,
)

NOW = datetime(2026, 10, 16, 6, 42, tzinfo=UTC)


def _snapshot(now: datetime = NOW, **changes: object) -> Snapshot:
    defaults = dict(
        timestamp=now,
        battery_soc=84.0,
        battery_power_kw=0.8,
        source_data_age_seconds=9.0,
        source_age_seconds={
            "battery_soc": 9.0,
            "battery_power_kw": 9.0,
            "house_load_kw": 9.0,
            "grid_import_kw": 9.0,
        },
        next_offpeak_start=NOW + timedelta(hours=17),
        house_load_kw=0.7,
        grid_import_kw=0.01,
        ev_connected=False,
        ev_charging=False,
        ev_power_kw=None,
        ev_power_age_seconds=None,
    )
    defaults.update(changes)
    return Snapshot(**defaults)


def _export(
    snapshot: Snapshot, proof: PaidAgileUnpluggedContinuity, now: datetime
) -> tuple:
    control = ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_economic_preemptive_export",
        desired_work_mode="Feed-in First",
        desired_battery_export_power_kw=5.753,
        desired_battery_to_home_power_kw=0.7,
        desired_total_discharge_power_kw=6.453,
        desired_grid_export_allowed=True,
        plan_safe=True,
        data_fresh=True,
    )
    return guard_paid_agile_physical_export(
        control,
        snapshot,
        SimpleNamespace(
            ready=True,
            expected_house_remaining_today_kwh=17.546,
            expected_solar_remaining_today_kwh=22.763,
            confidence_percent=90.0,
        ),
        SimulationConfig(
            battery_capacity_kwh=56.42,
            discharge_efficiency=0.95,
            battery_reserve_percent=15.0,
        ),
        ControlConfig(stale_data_seconds=180),
        now=now,
        ev_export_safe=True,
        ev_export_evidence="bounded_unplugged_physical_source_grace",
        unplugged_continuity=proof,
    )


def test_explicit_unplugged_without_power_enters_physical_paid_export() -> None:
    proof = PaidAgileUnpluggedContinuity()
    snapshot = _snapshot()
    assert proof.assess(snapshot, now=NOW)
    assert proof.status["assessment"] == "permitted_explicit_unplugged_physical_proof"
    planned, report = _export(snapshot, proof, NOW)
    assert report["status"] == "permitted_with_physical_house_budget"
    assert planned.desired_battery_export_power_kw == pytest.approx(5.753)


def test_asynchronous_cloud_power_age_can_arm_with_explicit_disconnect() -> None:
    proof = PaidAgileUnpluggedContinuity()
    snapshot = _snapshot(ev_power_kw=0.0, ev_power_age_seconds=63.0)
    assert proof.assess(snapshot, now=NOW)
    assert _export(snapshot, proof, NOW)[0].desired_battery_export_power_kw > 0


def test_simultaneously_unavailable_after_fresh_disconnection_has_bounded_grace() -> (
    None
):
    proof = PaidAgileUnpluggedContinuity()
    proof.assess(_snapshot(), now=NOW)
    at = NOW + timedelta(seconds=50)
    missing = _snapshot(at, ev_connected=None, ev_charging=None)
    assert proof.assess(missing, now=at)
    assert _export(missing, proof, at)[0].desired_battery_export_power_kw > 0
    expired = NOW + timedelta(seconds=91)
    assert not proof.assess(
        _snapshot(expired, ev_connected=None, ev_charging=None), now=expired
    )
    assert proof.status["assessment"] == "outage_grace_expired_or_physical_veto"


@pytest.mark.parametrize(
    "changes",
    [
        {"ev_connected": True},
        {"ev_charging": True},
        {"ev_power_kw": 7.0},
        {"ev_power_kw": 0.2},
        {"ev_power_kw": -0.1},
        {"house_load_kw": None},
        {"grid_import_kw": None},
        {"grid_import_kw": 0.6},
        {"source_age_seconds": {"house_load_kw": 80.0, "grid_import_kw": 9.0}},
        {"stale_fields": ("grid_import_kw",)},
    ],
)
def test_explicit_unplugged_requires_safe_fresh_physical_evidence(
    changes: dict[str, object],
) -> None:
    proof = PaidAgileUnpluggedContinuity()
    snapshot = _snapshot(**changes)
    assert not proof.assess(snapshot, now=NOW)
    assert _export(snapshot, proof, NOW)[0].desired_battery_export_power_kw == 0


def test_missing_disconnection_on_first_scan_is_not_permission() -> None:
    proof = PaidAgileUnpluggedContinuity()
    for connection in (None, True):
        snapshot = _snapshot(ev_connected=connection, ev_charging=None)
        assert not proof.assess(snapshot, now=NOW)
        assert _export(snapshot, proof, NOW)[0].desired_battery_export_power_kw == 0


def test_connected_event_immediately_clears_existing_unplugged_evidence() -> None:
    proof = PaidAgileUnpluggedContinuity()
    assert proof.assess(_snapshot(), now=NOW)
    plugged = _snapshot(NOW + timedelta(seconds=3), ev_connected=True)
    assert not proof.assess(plugged, now=plugged.timestamp)
    assert proof.status["last_confirmed_unplugged_at"] is None
    missing = _snapshot(NOW + timedelta(seconds=6), ev_connected=None)
    assert not proof.assess(missing, now=missing.timestamp)


def test_restart_does_not_inherit_unplugged_source_proof() -> None:
    proof = PaidAgileUnpluggedContinuity()
    assert proof.assess(_snapshot(), now=NOW)
    restarted = PaidAgileUnpluggedContinuity()
    missing = _snapshot(NOW + timedelta(seconds=15), ev_connected=None)
    assert not restarted.assess(missing, now=missing.timestamp)
    assert (
        _export(missing, restarted, missing.timestamp)[
            0
        ].desired_battery_export_power_kw
        == 0
    )


def test_diagnostics_exposes_why_proof_is_not_armed() -> None:
    coordinator = (
        Path(__file__).parents[1] / "custom_components" / "kems" / "coordinator.py"
    ).read_text(encoding="utf-8")
    assert (
        '"agile_unplugged_source_proof": self._paid_agile_unplugged_continuity.status'
        in coordinator
    )
    proof = PaidAgileUnpluggedContinuity()
    assert proof.status["assessment"] == "no_unplugged_proof"
    proof.assess(_snapshot(ev_connected=None), now=NOW)
    assert proof.status["assessment"] == "awaiting_fresh_explicit_unplugged_status"
