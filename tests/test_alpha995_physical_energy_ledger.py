"""Alpha9.95: physically anchored, gap-debited paid Agile energy evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from kems_core import ControlConfig, ControlState, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import guard_paid_agile_physical_export
from kems_core.agile_physical_energy import PaidAgilePhysicalEnergyTracker

START = datetime(2026, 10, 14, 9, 20, 40, tzinfo=UTC)
SIM = SimulationConfig(
    battery_capacity_kwh=56.42,
    discharge_efficiency=0.95,
    battery_reserve_percent=15.0,
)
CONFIG = ControlConfig(stale_data_seconds=180)


def _snapshot(
    when: datetime,
    *,
    soc_at: datetime = START - timedelta(seconds=5),
    soc: float = 100.0,
    battery_kw: float | None = 0.0,
    power_age: float = 1.0,
    **changes: object,
) -> Snapshot:
    values = dict(
        timestamp=when,
        battery_soc=soc,
        battery_power_kw=battery_kw,
        source_age_seconds={
            "battery_soc": (when - soc_at).total_seconds(),
            "battery_power_kw": power_age,
            "house_load_kw": 2.0,
        },
        source_data_age_seconds=2.0,
        ev_connected=False,
        ev_charging=False,
        ev_power_kw=0.0,
        ev_power_age_seconds=5.0,
        next_offpeak_start=when + timedelta(hours=6),
    )
    values.update(changes)
    return Snapshot(**values)


def _control() -> ControlState:
    return ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_price_optimised",
        desired_work_mode="Feed-in First",
        desired_battery_to_home_power_kw=0.8,
        desired_battery_export_power_kw=4.0,
        desired_total_discharge_power_kw=4.8,
        desired_grid_export_allowed=True,
        data_fresh=True,
        plan_safe=True,
    )


def _guard(snap: Snapshot, evidence) -> tuple[ControlState, dict]:
    return guard_paid_agile_physical_export(
        _control(),
        snap,
        SimpleNamespace(
            ready=True,
            expected_house_remaining_today_kwh=12.0,
            expected_solar_remaining_today_kwh=0.0,
            confidence_percent=0.0,
        ),
        SIM,
        CONFIG,
        now=snap.timestamp,
        ev_export_safe=True,
        ev_export_evidence="confirmed_unplugged",
        physical_energy_evidence=evidence,
    )


def test_unchanged_100_percent_soc_more_than_two_hours_permits_bounded_export() -> None:
    tracker = PaidAgilePhysicalEnergyTracker()
    recent = _snapshot(START)
    first = tracker.observe(recent, SIM, CONFIG, now=START)
    assert first.lower_bound_kwh is None
    last = first
    for minute in range(1, 136):
        when = START + timedelta(minutes=minute)
        recent = _snapshot(when)
        last = tracker.observe(recent, SIM, CONFIG, now=when)
    assert last.lower_bound_kwh is not None
    assert 53.0 < last.lower_bound_kwh < 56.42
    assert last.source_soc_percent == 100.0
    assert last.samples == 136
    assert last.status == "verified_power_continuity_with_margin"
    planned, guard = _guard(recent, last)
    assert planned.desired_battery_export_power_kw == 4.0
    assert guard["status"] == "permitted_with_physical_house_budget"
    assert guard["soc_freshness_basis"] == (
        "session_physical_energy_ledger_with_gap_debits"
    )
    assert guard["physical_soc_lower_bound_percent"] < 100.0
    assert guard["minimum_battery_reserve_kwh"] == 8.463


def test_unobserved_five_minute_history_gaps_use_full_discharge_budget() -> None:
    tracker = PaidAgilePhysicalEnergyTracker()
    snapshots = [_snapshot(START + timedelta(minutes=5 * i)) for i in range(4)]
    tracker.replay(snapshots, SIM, CONFIG, now=snapshots[-1].timestamp)
    evidence = tracker.observe(
        _snapshot(snapshots[-1].timestamp + timedelta(minutes=1)),
        SIM,
        CONFIG,
        now=snapshots[-1].timestamp + timedelta(minutes=1),
    )
    assert evidence.lower_bound_kwh is not None
    assert evidence.worst_case_gap_kwh >= 2.63
    assert evidence.lower_bound_kwh <= 56.42 - 2.63
    assert evidence.status == "verified_power_continuity_with_margin"


def test_cold_restart_cannot_seed_from_old_soc_without_history() -> None:
    when = START + timedelta(hours=3)
    snap = _snapshot(when)
    tracker = PaidAgilePhysicalEnergyTracker()
    evidence = tracker.observe(snap, SIM, CONFIG, now=when)
    assert evidence.lower_bound_kwh is None
    assert evidence.status == "awaiting_recent_physical_soc_anchor"
    blocked, report = _guard(snap, evidence)
    assert blocked.desired_battery_export_power_kw == 0.0
    assert "too old to bound" in report["reason"]


def test_power_dropout_debits_maximum_and_fails_closed_until_recovery() -> None:
    tracker = PaidAgilePhysicalEnergyTracker()
    tracker.observe(_snapshot(START), SIM, CONFIG, now=START)
    missing_at = START + timedelta(minutes=1)
    missing = _snapshot(missing_at, battery_kw=None, power_age=200.0)
    evidence = tracker.observe(missing, SIM, CONFIG, now=missing_at)
    assert evidence.lower_bound_kwh is None
    assert evidence.status == "power_unavailable_no_export"
    recovered_at = missing_at + timedelta(minutes=1)
    recovered = _snapshot(recovered_at, battery_kw=0.0)
    evidence = tracker.observe(recovered, SIM, CONFIG, now=recovered_at)
    assert evidence.lower_bound_kwh is None
    assert evidence.worst_case_gap_kwh > 0.35
    one_more = recovered_at + timedelta(minutes=1)
    snap = _snapshot(one_more)
    evidence = tracker.observe(snap, SIM, CONFIG, now=one_more)
    assert evidence.lower_bound_kwh is not None
    assert evidence.pessimistic_discharge_kwh > 0.35


def test_silent_gap_over_fifteen_minutes_removes_export_permission() -> None:
    tracker = PaidAgilePhysicalEnergyTracker()
    tracker.observe(_snapshot(START), SIM, CONFIG, now=START)
    tracker.observe(
        _snapshot(START + timedelta(minutes=1)),
        SIM,
        CONFIG,
        now=START + timedelta(minutes=1),
    )
    when = START + timedelta(minutes=17)
    evidence = tracker.observe(_snapshot(when), SIM, CONFIG, now=when)
    assert evidence.lower_bound_kwh is None
    assert evidence.status == "physical_observation_timeline_interrupted"


def test_fresh_newer_real_soc_can_reanchor_but_stale_soc_cannot() -> None:
    tracker = PaidAgilePhysicalEnergyTracker()
    tracker.observe(_snapshot(START), SIM, CONFIG, now=START)
    at = START + timedelta(minutes=1)
    tracker.observe(_snapshot(at, battery_kw=3.0), SIM, CONFIG, now=at)
    at += timedelta(minutes=1)
    refreshed = _snapshot(at, soc_at=at - timedelta(seconds=2), soc=97.0)
    evidence = tracker.observe(refreshed, SIM, CONFIG, now=at)
    assert evidence.lower_bound_kwh is not None
    assert evidence.source_soc_percent == 97.0
    assert evidence.status == "new_verified_soc_anchor"
    inconsistent_at = at + timedelta(minutes=1)
    inconsistent = _snapshot(
        inconsistent_at, soc_at=at - timedelta(seconds=2), soc=98.0
    )
    conflict = tracker.observe(inconsistent, SIM, CONFIG, now=inconsistent_at)
    assert conflict.lower_bound_kwh is None
    assert conflict.status == "soc_source_timestamp_or_value_conflict"


def test_stale_soc_source_and_unsafe_ev_still_fail_closed() -> None:
    tracker = PaidAgilePhysicalEnergyTracker()
    tracker.observe(_snapshot(START), SIM, CONFIG, now=START)
    at = START + timedelta(hours=2)
    valid = _snapshot(at)
    # Replay cannot claim two hours of an unobserved power trace.
    assert tracker.observe(valid, SIM, CONFIG, now=at).lower_bound_kwh is None
    for condition in (
        {"stale_fields": ("battery_soc",)},
        {"ev_connected": True, "ev_power_kw": 0.0},
        {"ev_power_kw": 2.0, "ev_charging": True},
        {"source_data_age_seconds": 181.0},
    ):
        scan = _snapshot(START, **condition)
        # An unknown/stale EV is never authorised by physical battery proof.
        decided, _ = _guard(scan, None)
        assert decided.desired_battery_export_power_kw == 0.0


def test_physical_proof_cannot_be_reused_for_another_scan() -> None:
    tracker = PaidAgilePhysicalEnergyTracker()
    tracker.observe(_snapshot(START), SIM, CONFIG, now=START)
    at = START + timedelta(minutes=1)
    proof = tracker.observe(_snapshot(at), SIM, CONFIG, now=at)
    assert proof.lower_bound_kwh is not None
    future = START + timedelta(hours=2)
    blocked, detail = _guard(_snapshot(future), proof)
    assert blocked.desired_battery_export_power_kw == 0.0
    assert "too old to bound" in detail["reason"]


def test_normal_zero_export_and_confirmed_cheap_are_untouched() -> None:
    from dataclasses import replace

    snap = _snapshot(START)
    idle = replace(_control(), desired_battery_export_power_kw=0.0)
    result, report = guard_paid_agile_physical_export(
        idle,
        snap,
        None,
        SIM,
        CONFIG,
        now=START,
    )
    assert result is idle
    assert report["status"] == "no_deliberate_export_requested"
    cheap, report = guard_paid_agile_physical_export(
        _control(),
        _snapshot(START, off_peak=True),
        None,
        SIM,
        CONFIG,
        now=START,
    )
    assert cheap is not None
    assert report["status"] == "higher_priority_cheap_or_event"


def test_hardware_min_soc_and_no_paid_export_paths_are_unchanged() -> None:
    from pathlib import Path

    root = Path(__file__).parents[1] / "custom_components" / "kems"
    coordinator = (root / "coordinator.py").read_text(encoding="utf-8")
    core = (root / "kems_core" / "agile_live_reserve.py").read_text(encoding="utf-8")
    backend = (root / "kems_core" / "control_write_authority.py").read_text(
        encoding="utf-8"
    )
    assert "if tariff_type == EXPORT_TARIFF_TYPE_AGILE:" in coordinator
    assert "self._paid_agile_physical_energy.reset()" in coordinator
    assert "_MIN_PLANNING_RESERVE_PERCENT = 15.0" in core
    assert "effective_export_limit_kw" in backend
    assert "no_paid_export_mode" in backend
