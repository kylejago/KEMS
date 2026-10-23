"""Alpha9.127 regression: verified Back-up recovery under normal house import.

These tests never grant FoxESS write authority or skip paid-export stage proof.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from kems_core.commissioning_evidence import (
    _released_backup_ct_recovery,
    _released_backup_distinct_readbacks,
    assess_foxess_power_balance,
)
from kems_core.foxess_ac_balance import assess_foxess_ac_side_sample

RELEASE = datetime(2026, 10, 23, 17, 7, 57, tzinfo=UTC)


def _probe_power(power: float, reported: datetime) -> dict[str, object]:
    return {
        "value": power,
        "unit": "kW",
        "last_reported": reported.isoformat(),
    }


def _backup(
    seconds: int,
    *,
    grid_import: float = 1.955,
    house_load: float = 1.959,
    battery: float = 0.2,
) -> SimpleNamespace:
    now = RELEASE + timedelta(seconds=seconds)
    ct_at = now - timedelta(seconds=8)
    ac_at = RELEASE + timedelta(seconds=26)
    return SimpleNamespace(
        timestamp=now,
        battery_soc=52.0,
        battery_power_kw=battery,
        solar_power_kw=0.0,
        house_load_kw=house_load,
        grid_import_kw=grid_import,
        grid_export_kw=0.0,
        raw_grid_import_kw=grid_import,
        raw_grid_export_kw=0.0,
        grid_flow_mode="separate_positive_sources",
        ev_connected=False,
        ev_charging=False,
        ev_power_kw=0.0,
        ev_power_age_seconds=8.0,
        source_age_seconds={"house_load_kw": 8.0, "battery_power_kw": 8.0},
        stale_fields=(),
        foxess_balance_probe={
            "observed_after_snapshot_at": (
                now + timedelta(milliseconds=20)
            ).isoformat(),
            "last_write_result": "KEMS FoxESS ownership released safely",
            "last_applied_action": None,
            "last_write_at": RELEASE.isoformat(),
            "commands_permitted_previous_cycle": False,
            "work_mode": {"value": "Back-up", "status": "PASS"},
            "inverter_ac_output": _probe_power(0.0, ac_at),
            "grid_ct": _probe_power(-grid_import, ct_at),
            "inverter_reported_load": _probe_power(house_load, ct_at),
        },
    )


def _ordinary(now: datetime) -> SimpleNamespace:
    r = _backup(int((now - RELEASE).total_seconds()), grid_import=0.2, house_load=0.2, battery=0.0)
    r.foxess_balance_probe["inverter_ac_output"] = _probe_power(
        0.0, now - timedelta(seconds=8)
    )
    r.foxess_balance_probe["work_mode"] = {"value": "Self Use", "status": "PASS"}
    return r


def _transient() -> SimpleNamespace:
    now = RELEASE - timedelta(seconds=30)
    write_at = now - timedelta(seconds=10)
    r = _ordinary(now)
    r.battery_power_kw = 3.724
    r.house_load_kw = 3.588
    r.grid_import_kw = 0.0
    r.raw_grid_import_kw = 0.0
    r.grid_export_kw = 1.439
    r.raw_grid_export_kw = 1.439
    p = r.foxess_balance_probe
    p["last_applied_action"] = "self_use"
    p["last_write_result"] = "Alpha9.67 bounded FoxESS command applied"
    p["last_write_at"] = write_at.isoformat()
    p["inverter_ac_output"] = _probe_power(
        3.589, write_at + timedelta(seconds=1)
    )
    p["grid_ct"] = _probe_power(1.439, write_at + timedelta(seconds=1))
    p["inverter_reported_load"] = _probe_power(
        3.588, write_at + timedelta(seconds=1)
    )
    return r


def _replay(last: SimpleNamespace, second: SimpleNamespace):
    earlier = [
        _ordinary(RELEASE - timedelta(minutes=30 - index))
        for index in range(28)
    ]
    return assess_foxess_power_balance(
        [*earlier, _transient(), last, second],
        positive_is_discharge=True,
        quarantine_self_use_settling=True,
    )


def test_real_1813_backup_with_two_new_reports_can_requalify() -> None:
    first, second = _backup(180), _backup(240)
    assert assess_foxess_ac_side_sample(first)["status"] == "not_time_aligned"
    assert _released_backup_ct_recovery(
        first, ac_cross_check=assess_foxess_ac_side_sample(first)
    )
    result = _replay(first, second)
    assert result.state == "balanced"
    assert result.ready is True
    assert result.eligible_samples == 30
    assert result.balance_percent == 100.0
    assert result.ac_side_audit["post_command_settling_quarantined_count"] == 1
    assert result.ac_side_audit["post_safe_release_latest_pair_distinct"] is True


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("grid_import_kw", 3.5),
        ("ev_connected", True),
        ("ev_charging", True),
        ("ev_power_kw", 0.8),
        ("ev_power_age_seconds", 50.0),
        ("solar_power_kw", 0.5),
        ("battery_power_kw", 0.8),
        ("grid_export_kw", 0.2),
    ],
)
def test_extended_load_never_accepts_unsafe_source(change: str, value: object) -> None:
    obs = _backup(180)
    setattr(obs, change, value)
    check = assess_foxess_ac_side_sample(obs)
    assert not _released_backup_ct_recovery(obs, ac_cross_check=check)


def test_extended_load_requires_actual_house_import_match() -> None:
    obs = _backup(180, grid_import=1.955, house_load=2.7)
    assert not _released_backup_ct_recovery(
        obs, ac_cross_check=assess_foxess_ac_side_sample(obs)
    )


def test_fresh_nonzero_ac_or_wrong_mode_cannot_be_recovery_evidence() -> None:
    obs = _backup(180)
    obs.foxess_balance_probe["work_mode"]["value"] = "Self Use"
    assert not _released_backup_ct_recovery(
        obs, ac_cross_check=assess_foxess_ac_side_sample(obs)
    )
    obs = _backup(180)
    obs.foxess_balance_probe["inverter_ac_output"] = _probe_power(
        1.9, obs.timestamp - timedelta(seconds=8)
    )
    assert not _released_backup_ct_recovery(
        obs, ac_cross_check=assess_foxess_ac_side_sample(obs)
    )


def test_cached_ct_or_house_reports_do_not_count_as_two_proofs() -> None:
    first, second = _backup(180), _backup(195)
    # Both snapshot times are distinct, but the FoxESS CT/load reports repeat.
    for field in ("grid_ct", "inverter_reported_load"):
        second.foxess_balance_probe[field]["last_reported"] = (
            first.foxess_balance_probe[field]["last_reported"]
        )
    assert _released_backup_ct_recovery(
        second, ac_cross_check=assess_foxess_ac_side_sample(second)
    )
    assert not _released_backup_distinct_readbacks(first, second)
    result = _replay(first, second)
    assert result.state == "settling_unverified"
    assert result.ac_side_audit["post_safe_release_latest_pair_distinct"] is False


def test_cached_battery_readback_cannot_count_twice() -> None:
    first, second = _backup(180), _backup(195)
    second.source_age_seconds["battery_power_kw"] = 23.0
    assert not _released_backup_distinct_readbacks(first, second)
    assert _replay(first, second).state == "settling_unverified"


def test_two_ordinary_ac_proofs_remain_unchanged() -> None:
    last = _ordinary(RELEASE + timedelta(seconds=180))
    second = _ordinary(RELEASE + timedelta(seconds=240))
    result = _replay(last, second)
    assert result.ready is True
    assert result.ac_side_audit["post_safe_release_idle_proofs"] == 0


def test_safe_release_does_not_override_over_export_hard_stop() -> None:
    last, second = _backup(180), _backup(240)
    last.grid_export_kw = 7.1
    last.raw_grid_export_kw = 7.1
    result = _replay(last, second)
    assert result.state == "grid_export_limit_violation"
    assert result.ready is False
