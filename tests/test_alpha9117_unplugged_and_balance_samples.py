"""Alpha9.117 regressions: unplugged EV proof and bounded balance diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from kems_core import ControlConfig, ControlState, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import (
    PaidAgileUnpluggedContinuity,
    guard_paid_agile_physical_export,
)
from kems_core.commissioning_evidence import assess_foxess_power_balance

NOW = datetime(2026, 10, 20, 20, 30, tzinfo=UTC)


def _snapshot(**overrides: object) -> Snapshot:
    fields = dict(
        timestamp=NOW,
        battery_soc=80.0,
        battery_power_kw=0.25,
        source_data_age_seconds=9.0,
        source_age_seconds={
            "battery_soc": 9.0,
            "battery_power_kw": 9.0,
            "house_load_kw": 9.0,
            "grid_import_kw": 107.0,
        },
        next_offpeak_start=NOW + timedelta(hours=3),
        house_load_kw=0.5,
        grid_import_kw=0.0,
        ev_connected=False,
        ev_charging=False,
        ev_power_kw=None,
        ev_power_age_seconds=None,
    )
    fields.update(overrides)
    return Snapshot(**fields)


def _export(
    snapshot: Snapshot, proof: PaidAgileUnpluggedContinuity | None
) -> tuple[ControlState, dict]:
    control = ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_price_optimised",
        desired_work_mode="Feed-in First",
        desired_battery_export_power_kw=4.5,
        desired_battery_to_home_power_kw=0.5,
        desired_total_discharge_power_kw=5.0,
        desired_grid_export_allowed=True,
        data_fresh=True,
        plan_safe=True,
    )
    return guard_paid_agile_physical_export(
        control,
        snapshot,
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
        now=NOW,
        ev_export_safe=True,
        ev_export_evidence="bounded_unplugged_physical_source_grace",
        unplugged_continuity=proof,
    )


def test_fresh_explicit_unplugged_with_unchanged_zero_grid_allows_export() -> None:
    snapshot = _snapshot()
    proof = PaidAgileUnpluggedContinuity()
    assert proof.assess(snapshot, now=NOW)
    assert proof.status["assessment"] == "permitted_explicit_unplugged_physical_proof"
    applied, report = _export(snapshot, proof)
    assert applied.desired_battery_export_power_kw == pytest.approx(4.5)
    assert report["status"] == "permitted_with_physical_house_budget"


@pytest.mark.parametrize(
    "changes",
    [
        {"ev_connected": True},
        {"ev_connected": None},
        {"ev_charging": True},
        {"ev_power_kw": 0.2},
        {"ev_power_kw": 7.0},
        {"grid_import_kw": 0.5},
        {"house_load_kw": None},
        {"stale_fields": ("grid_import_kw",)},
        {"source_age_seconds": {"house_load_kw": 36.0, "grid_import_kw": 107.0}},
        {"source_age_seconds": {"house_load_kw": 9.0, "grid_import_kw": 181.0}},
    ],
)
def test_no_export_when_explicit_disconnection_or_physical_proof_missing(
    changes: dict[str, object],
) -> None:
    snapshot = _snapshot(**changes)
    proof = PaidAgileUnpluggedContinuity()
    assert not proof.assess(snapshot, now=NOW)
    applied, report = _export(snapshot, proof)
    assert applied.desired_battery_export_power_kw == 0.0, report


@pytest.mark.parametrize(
    "house_kw, import_kw, permitted",
    [
        (0.305, 0.307, True),  # real Alpha9.117 observation
        (0.5, 0.65, True),  # house import with bounded CT discrepancy
        (0.305, 0.9, False),  # unexplained physical grid demand
        (0.0, 0.35, False),  # no home demand to explain import
    ],
)
def test_confirmed_unplugged_house_grid_import_not_mistaken_for_ev(
    house_kw: float, import_kw: float, permitted: bool
) -> None:
    snapshot = _snapshot(house_load_kw=house_kw, grid_import_kw=import_kw)
    proof = PaidAgileUnpluggedContinuity()
    assert proof.assess(snapshot, now=NOW) is permitted
    applied, _ = _export(snapshot, proof)
    assert (applied.desired_battery_export_power_kw > 0.0) is permitted


def test_uncertain_ev_cannot_use_house_load_to_authorise_export() -> None:
    snapshot = _snapshot(
        ev_connected=None,
        ev_charging=None,
        house_load_kw=0.305,
        grid_import_kw=0.307,
    )
    proof = PaidAgileUnpluggedContinuity()
    assert not proof.assess(snapshot, now=NOW)
    applied, _ = _export(snapshot, proof)
    assert applied.desired_battery_export_power_kw == 0.0


def test_uncertain_connection_does_not_inherit_relaxed_grid_age() -> None:
    proof = PaidAgileUnpluggedContinuity()
    fresh = _snapshot(source_age_seconds={"house_load_kw": 9.0, "grid_import_kw": 9.0})
    assert proof.assess(fresh, now=NOW)
    uncertain = _snapshot(
        timestamp=NOW + timedelta(seconds=20),
        ev_connected=None,
        ev_charging=None,
        ev_power_kw=None,
        source_age_seconds={"house_load_kw": 9.0, "grid_import_kw": 107.0},
    )
    assert not proof.assess(uncertain, now=NOW + timedelta(seconds=20))


def test_cannot_spoof_unplugged_permission_without_session_proof() -> None:
    applied, report = _export(_snapshot(), None)
    assert applied.desired_battery_export_power_kw == 0.0, report


def _physical_record(i: int, *, bad: bool) -> SimpleNamespace:
    timestamp = NOW + timedelta(seconds=25 * i)
    return SimpleNamespace(
        timestamp=timestamp,
        solar_power_kw=0.0,
        battery_power_kw=7.2 if bad else 2.0,
        house_load_kw=0.5,
        grid_import_kw=0.0,
        grid_export_kw=0.0 if bad else 1.5,
        battery_soc=60.0,
        stale_fields=(),
        source_age_seconds={
            "battery_power_kw": 9.0,
            "solar_power_kw": 100.0,
            "grid_import_kw": "invalid" if i == 0 else 100.0,
            "grid_export_kw": 9.0,
            "house_load_kw": 9.0,
        },
    )


def test_power_balance_threshold_unchanged_and_failed_samples_bounded() -> None:
    records = [_physical_record(i, bad=i < 7) for i in range(60)]
    failed = assess_foxess_power_balance(records, positive_is_discharge=True)
    assert not failed.ready
    assert failed.balanced_samples == 53
    assert failed.balance_percent == 88.3
    assert len(failed.failed_samples) == 7
    first = failed.to_dict()["failed_samples"][0]
    assert first["timestamp"] == NOW.isoformat()
    assert first["power_kw"]["battery_power_kw"] == 7.2
    assert first["source_ages_seconds"]["grid_import_kw"] is None
    assert first["residual_kw"] == pytest.approx(6.7)
    assert first["tolerance_kw"] == pytest.approx(1.08)
    assert first["foxess_mode_probe"] == {}

    recovered = assess_foxess_power_balance(
        [_physical_record(i, bad=i < 4) for i in range(60)],
        positive_is_discharge=True,
    )
    assert recovered.ready
    assert recovered.balanced_samples == 56
    assert len(recovered.failed_samples) == 4

    many = assess_foxess_power_balance(
        [_physical_record(i, bad=i < 12) for i in range(60)],
        positive_is_discharge=True,
    )
    assert len(many.failed_samples) == 8
    assert (
        many.failed_samples[0]["timestamp"]
        == (NOW + timedelta(seconds=25 * 4)).isoformat()
    )
