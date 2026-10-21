"""Alpha9.105: verified-unplugged Ohme outages must not cancel paid Agile export.

Only live paid Agile gains a bounded physical meter corroboration bridge. A
connected EV, a positive charger reading, stale site telemetry, or an expired
outage remains blocked. The legacy direct-zero and connected-idle gates stay.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from kems_core import ControlConfig, ControlState, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import (
    PaidAgileUnpluggedContinuity,
    assess_paid_agile_ev_continuity,
    guard_paid_agile_physical_export,
)

NOW = datetime(2026, 10, 16, 5, 30, tzinfo=UTC)


def _snapshot(at: datetime = NOW, **changes: object) -> Snapshot:
    inputs = dict(
        timestamp=at,
        battery_soc=86.0,
        battery_power_kw=0.823,
        source_data_age_seconds=9.1,
        source_age_seconds={
            "battery_soc": 9.1,
            "battery_power_kw": 9.1,
            "house_load_kw": 9.1,
            "grid_import_kw": 9.1,
        },
        next_offpeak_start=at + timedelta(hours=17),
        house_load_kw=0.695,
        grid_import_kw=0.0,
        ev_connected=False,
        ev_charging=False,
        ev_power_kw=0.0,
        ev_power_age_seconds=8.0,
    )
    inputs.update(changes)
    return Snapshot(**inputs)


def _cloud_outage(at: datetime, **changes: object) -> Snapshot:
    fields = dict(
        ev_connected=None,
        ev_charging=None,
        ev_power_kw=None,
        ev_power_age_seconds=None,
        house_load_kw=0.72,
        grid_import_kw=0.0,
    )
    fields.update(changes)
    return _snapshot(at, **fields)


def _guard(
    snap: Snapshot,
    proof: PaidAgileUnpluggedContinuity | None,
    *,
    when: datetime,
    evidence: str = "bounded_unplugged_physical_source_grace",
    permission: bool = True,
) -> tuple[ControlState, dict]:
    plan = ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_price_optimised",
        desired_work_mode="Feed-in First",
        desired_battery_export_power_kw=5.177,
        desired_battery_to_home_power_kw=0.695,
        desired_total_discharge_power_kw=5.872,
        desired_grid_export_allowed=True,
        data_fresh=True,
        plan_safe=True,
    )
    forecast = SimpleNamespace(
        ready=True,
        expected_house_remaining_today_kwh=3.0,
        expected_solar_remaining_today_kwh=0.0,
        confidence_percent=0.0,
    )
    return guard_paid_agile_physical_export(
        plan,
        snap,
        forecast,
        SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_reserve_percent=15.0,
            discharge_efficiency=0.95,
        ),
        ControlConfig(stale_data_seconds=180),
        now=when,
        ev_export_safe=permission,
        ev_export_evidence=evidence,
        unplugged_continuity=proof,
    )


def test_diagnostic_replay_all_ohme_sources_unavailable_permits_brief_outage() -> None:
    proof = PaidAgileUnpluggedContinuity()
    confirmed = _snapshot()
    assert not proof.assess(confirmed, now=NOW)
    fresh, anchor, label = assess_paid_agile_ev_continuity(
        confirmed, now=NOW, last_confirmed_unplugged_at=None
    )
    assert fresh and anchor == NOW and label == "confirmed_unplugged"
    at = NOW + timedelta(seconds=60)
    missing = _cloud_outage(at)
    direct, _anchor, _label = assess_paid_agile_ev_continuity(
        missing, now=at, last_confirmed_unplugged_at=anchor
    )
    assert direct is False
    assert proof.assess(missing, now=at) is True
    desired, report = _guard(missing, proof, when=at)
    assert report["status"] == "permitted_with_physical_house_budget"
    assert desired.desired_battery_export_power_kw == pytest.approx(5.177)
    assert report["ev_export_evidence"] == "bounded_unplugged_physical_source_grace"


def test_same_outage_grace_expires_and_cannot_rearm_without_ohme() -> None:
    proof = PaidAgileUnpluggedContinuity()
    proof.assess(_snapshot(), now=NOW)
    outage_at = NOW + timedelta(seconds=60)
    assert proof.assess(_cloud_outage(outage_at), now=outage_at)
    at = outage_at + timedelta(seconds=91)
    lost = _cloud_outage(at)
    assert not proof.assess(lost, now=at)
    assert _guard(lost, proof, when=at)[0].desired_battery_export_power_kw == 0
    assert not proof.assess(
        _cloud_outage(at + timedelta(seconds=1)), now=at + timedelta(seconds=1)
    )
    # A new fresh physical unplugged+zero observation can re-arm.
    recovered_at = at + timedelta(seconds=10)
    assert not proof.assess(_snapshot(recovered_at), now=recovered_at)
    again = recovered_at + timedelta(seconds=8)
    assert proof.assess(_cloud_outage(again), now=again)


@pytest.mark.parametrize(
    "changes",
    [
        {"ev_connected": True},
        {"ev_charging": True},
        {"ev_power_kw": 0.11},
        {"ev_power_kw": 7.0},
        {"ev_power_kw": -1.0},
        {"house_load_kw": 3.5},
        {"house_load_kw": None},
        {"grid_import_kw": 0.5},
        {"grid_import_kw": None},
        {"source_age_seconds": {"house_load_kw": 60.0, "grid_import_kw": 9.0}},
        {"source_age_seconds": {"house_load_kw": 9.0, "grid_import_kw": 60.0}},
        {"stale_fields": ("grid_import_kw",)},
        {"stale_fields": ("house_load_kw",)},
    ],
)
def test_real_charging_or_missing_meters_immediately_cancel_outage_grace(
    changes: dict[str, object],
) -> None:
    proof = PaidAgileUnpluggedContinuity()
    proof.assess(_snapshot(), now=NOW)
    at = NOW + timedelta(seconds=50)
    unsafe = _cloud_outage(at, **changes)
    assert not proof.assess(unsafe, now=at)
    assert _guard(unsafe, proof, when=at)[0].desired_battery_export_power_kw == 0


def test_no_fake_evidence_and_no_restart_carryover() -> None:
    at = NOW + timedelta(seconds=40)
    lost = _cloud_outage(at)
    empty = PaidAgileUnpluggedContinuity()
    assert not empty.assess(lost, now=at)
    for label, proof in (
        ("bounded_unplugged_physical_source_grace", None),
        ("bounded_unplugged_physical_source_grace", empty),
        ("confirmed_unplugged", empty),
    ):
        requested, _ = _guard(lost, proof, when=at, evidence=label)
        assert requested.desired_battery_export_power_kw == 0
    proof = PaidAgileUnpluggedContinuity()
    proof.assess(_snapshot(), now=NOW)
    assert proof.assess(lost, now=at)
    for label in ("confirmed_unplugged", "bounded_connected_idle_source_grace"):
        requested, _ = _guard(lost, proof, when=at, evidence=label)
        assert requested.desired_battery_export_power_kw == 0
    assert (
        _guard(lost, proof, when=at, permission=False)[
            0
        ].desired_battery_export_power_kw
        == 0
    )


def test_verified_plugged_in_idle_never_arms_unplugged_outage() -> None:
    proof = PaidAgileUnpluggedContinuity()
    proof.assess(_snapshot(ev_connected=True), now=NOW)
    at = NOW + timedelta(seconds=50)
    assert not proof.assess(_cloud_outage(at), now=at)


def test_only_agile_branch_passes_verified_unplugged_proof() -> None:
    from pathlib import Path

    coordinator = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "kems"
        / "coordinator.py"
    ).read_text(encoding="utf-8")
    assert "self._paid_agile_unplugged_continuity.assess(" in coordinator
    assert (
        'ev_export_evidence = "bounded_unplugged_physical_source_grace"' in coordinator
    )
    assert "unplugged_continuity=self._paid_agile_unplugged_continuity" in coordinator
    assert "self._paid_agile_unplugged_continuity.clear()" in coordinator



def _fresh_coherent_export_with_aged_zero_import(
    at: datetime, **changes: object
) -> Snapshot:
    """Replay Alpha9.118's 17:08 KH7 split-grid cohort and stale zero import."""
    ac_kw = 5.512
    export_kw = 5.255
    house_kw = 0.263
    meter_at = (at - timedelta(seconds=9)).isoformat()
    fields: dict[str, object] = {
        "house_load_kw": house_kw,
        "grid_import_kw": 0.0,
        "grid_export_kw": export_kw,
        "raw_grid_import_kw": 0.0,
        "raw_grid_export_kw": export_kw,
        "grid_flow_mode": "separate_positive_sources",
        "source_age_seconds": {
            "house_load_kw": 9.0,
            "grid_import_kw": 2633.5,
            "grid_export_kw": 9.0,
            "battery_soc": 9.0,
            "battery_power_kw": 9.0,
        },
        "foxess_balance_probe": {
            "inverter_ac_output": {
                "value": ac_kw,
                "last_reported": meter_at,
            },
            "grid_ct": {"value": export_kw, "last_reported": meter_at},
            "inverter_reported_load": {
                "value": house_kw,
                "last_reported": meter_at,
            },
        },
    }
    fields.update(changes)
    return _snapshot(at, **fields)


def test_alpha9119_fresh_split_ct_keeps_unplugged_export_during_brief_ohme_loss() -> (
    None
):
    proof = PaidAgileUnpluggedContinuity()
    # Fresh explicit disconnection arms the proof even when the cloud Ohme
    # power entity itself is unavailable; the unchanged zero import alone
    # must NOT be considered fresh.
    anchored = _fresh_coherent_export_with_aged_zero_import(
        NOW, ev_power_kw=None, ev_power_age_seconds=None
    )
    assert proof.assess(anchored, now=NOW)
    assert proof.status["assessment"] == "permitted_explicit_unplugged_physical_proof"
    at = NOW + timedelta(seconds=45)
    outage = _fresh_coherent_export_with_aged_zero_import(
        at,
        ev_connected=None,
        ev_charging=None,
        ev_power_kw=None,
        ev_power_age_seconds=None,
    )
    assert proof.assess(outage, now=at)
    desired, report = _guard(outage, proof, when=at)
    assert report["status"] == "permitted_with_physical_house_budget"
    assert desired.desired_battery_export_power_kw == pytest.approx(5.177)
    # Never renew or perpetuate cloud outage from CT data alone.
    later = at + timedelta(seconds=91)
    assert not proof.assess(
        _fresh_coherent_export_with_aged_zero_import(
            later,
            ev_connected=None,
            ev_charging=None,
            ev_power_kw=None,
            ev_power_age_seconds=None,
        ),
        now=later,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"grid_flow_mode": "signed_grid_source"},
        {"raw_grid_import_kw": None},
        {"raw_grid_import_kw": 0.35},
        {"grid_import_kw": 0.35},
        {"raw_grid_export_kw": 0.0},
        {"grid_export_kw": 0.0},
        {"source_age_seconds": {
            "house_load_kw": 9.0,
            "grid_import_kw": 2633.5,
            "grid_export_kw": 45.0,
        }},
        {"stale_fields": ("grid_import_kw",)},
        {"stale_fields": ("grid_export_kw",)},
        {"foxess_balance_probe": {}},
        {"foxess_balance_probe": {
            "inverter_ac_output": {
                "value": 6.98,
                "last_reported": (NOW - timedelta(seconds=9)).isoformat(),
            },
            "grid_ct": {
                "value": 0.666,
                "last_reported": (NOW - timedelta(seconds=9)).isoformat(),
            },
            "inverter_reported_load": {
                "value": 0.272,
                "last_reported": (NOW - timedelta(seconds=9)).isoformat(),
            },
        }},
    ],
)
def test_alpha9119_split_ct_proof_refuses_stale_contradictory_or_untrusted_sources(
    change: dict[str, object],
) -> None:
    proof = PaidAgileUnpluggedContinuity()
    sample = _fresh_coherent_export_with_aged_zero_import(NOW, **change)
    assert not proof.assess(sample, now=NOW)
    assert _guard(sample, proof, when=NOW)[0].desired_battery_export_power_kw == 0.0


def test_alpha9119_ct_without_prior_disconnection_does_not_authorise_unknown_ev() -> (
    None
):
    proof = PaidAgileUnpluggedContinuity()
    at = NOW + timedelta(seconds=10)
    untrusted = _fresh_coherent_export_with_aged_zero_import(
        at,
        ev_connected=None,
        ev_charging=None,
        ev_power_kw=None,
        ev_power_age_seconds=None,
    )
    assert not proof.assess(untrusted, now=at)
    assert _guard(untrusted, proof, when=at)[0].desired_battery_export_power_kw == 0.0
