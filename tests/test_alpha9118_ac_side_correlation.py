"""Read-only KH7 AC correlation regression; never a hardware authority test."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from kems_core.commissioning_evidence import assess_foxess_power_balance
from kems_core.foxess_ac_balance import (
    assess_foxess_ac_ct_transition,
    assess_foxess_ac_side_sample,
    paid_export_stage_ct_conflict,
)

NOW = datetime(2026, 10, 21, 5, 34, 24, tzinfo=UTC)


def _observation(
    *,
    battery_kw: float = 1.516,
    inverter_kw: float = 0.34,
    ct_kw: float = -0.006,
    house_kw: float = 0.346,
    import_kw: float = 0.006,
    export_kw: float = 0.0,
    age_seconds: float = 9.0,
    report_lag_seconds: float = 1.0,
    unit: str = "kW",
) -> SimpleNamespace:
    reported_at = (NOW - timedelta(seconds=report_lag_seconds)).isoformat()
    return SimpleNamespace(
        timestamp=NOW,
        battery_soc=85.0,
        battery_power_kw=battery_kw,
        solar_power_kw=0.0,
        house_load_kw=house_kw,
        grid_import_kw=import_kw,
        grid_export_kw=export_kw,
        stale_fields=(),
        source_age_seconds={"house_load_kw": age_seconds},
        foxess_balance_probe={
            "observed_after_snapshot_at": (NOW + timedelta(seconds=1)).isoformat(),
            "force_discharge_stage_kw": 1.0,
            "last_applied_action": "force_discharge",
            "inverter_ac_output": {
                "value": inverter_kw,
                "unit": unit,
                "last_reported": reported_at,
            },
            "grid_ct": {
                "value": ct_kw,
                "unit": unit,
                "last_reported": reported_at,
            },
        },
    )


def test_original_mismatch_can_be_ac_consistent_without_granting_control() -> None:
    sample = _observation()
    result = assess_foxess_ac_side_sample(sample)
    assert result["status"] == "ac_cross_check_pass"
    assert result["inverter_ac_kw"] == pytest.approx(0.34)
    assert result["ac_implied_load_kw"] == pytest.approx(0.346)
    assert result["battery_dc_minus_inverter_ac_kw"] == pytest.approx(1.176)
    assert result["informational_only"]
    assert not result["independent_load_proven"]
    assert not result["hardware_write_authorised"]


def test_real_21_oct_0958_live_export_matches_ac_ct_within_four_watts() -> None:
    """Actual user-observed KH7 export: AC and CT align, DC is different."""
    sample = _observation(
        battery_kw=4.890,
        inverter_kw=6.940,
        ct_kw=6.778,
        house_kw=0.158,
        import_kw=0.0,
        export_kw=6.778,
        report_lag_seconds=0.001,
    )
    sample.timestamp = datetime(2026, 10, 21, 8, 58, 58, 590635, tzinfo=UTC)
    # Capture a coordinated group of readings (all within about 3 ms).
    sample.foxess_balance_probe["observed_after_snapshot_at"] = (
        sample.timestamp + timedelta(milliseconds=20)
    ).isoformat()
    for role in ("inverter_ac_output", "grid_ct"):
        sample.foxess_balance_probe[role]["last_reported"] = (
            sample.timestamp - timedelta(milliseconds=2)
        ).isoformat()
    sample.source_age_seconds["house_load_kw"] = 0.003

    result = assess_foxess_ac_side_sample(sample)
    assert result["status"] == "ac_cross_check_pass"
    assert result["ac_implied_load_kw"] == pytest.approx(0.162)
    assert result["foxess_reported_load_kw"] == pytest.approx(0.158)
    assert result["ac_load_residual_kw"] == pytest.approx(0.004)
    assert result["ct_split_residual_kw"] == pytest.approx(0.0)
    assert result["battery_dc_minus_inverter_ac_kw"] == pytest.approx(-2.05)
    assert result["informational_only"]
    assert not result["independent_load_proven"]
    assert not result["hardware_write_authorised"]


@pytest.mark.parametrize(
    "values",
    [
        dict(
            battery_kw=2.0,
            inverter_kw=1.8,
            ct_kw=1.4,
            house_kw=0.4,
            import_kw=0,
            export_kw=1.4,
        ),
        dict(
            battery_kw=-6.83,
            inverter_kw=-6.83,
            ct_kw=-7.38,
            house_kw=0.55,
            import_kw=7.38,
            export_kw=0,
        ),
    ],
)
def test_signed_ac_relationship_handles_export_and_grid_charging(
    values: dict[str, float],
) -> None:
    result = assess_foxess_ac_side_sample(_observation(**values))
    assert result["status"] == "ac_cross_check_pass"
    assert not result["hardware_write_authorised"]


def test_kilowatt_and_watt_unit_inputs_are_normalised() -> None:
    sample = _observation(inverter_kw=340.0, ct_kw=-6.0, unit="W")
    result = assess_foxess_ac_side_sample(sample)
    assert result["status"] == "ac_cross_check_pass"
    assert result["inverter_ac_kw"] == pytest.approx(0.34)


@pytest.mark.parametrize(
    "changes,expected",
    [
        (dict(report_lag_seconds=60), "not_time_aligned"),
        (dict(age_seconds=80), "house_report_stale"),
        (dict(unit="VA"), "invalid_or_missing_power"),
        (dict(ct_kw=1.0), "grid_ct_split_mismatch"),
        (dict(house_kw=1.6), "ac_load_mismatch"),
    ],
)
def test_freshness_units_and_genuine_inconsistency_are_not_hidden(
    changes: dict[str, object], expected: str
) -> None:
    result = assess_foxess_ac_side_sample(_observation(**changes))
    assert result["status"] == expected
    assert not result["hardware_write_authorised"]


def test_missing_probe_and_timestamps_fail_closed_in_diagnostics() -> None:
    sample = _observation()
    sample.foxess_balance_probe = {}
    assert assess_foxess_ac_side_sample(sample)["status"] == "missing_probe"
    sample = _observation()
    del sample.foxess_balance_probe["grid_ct"]["last_reported"]
    assert assess_foxess_ac_side_sample(sample)["status"] == "missing_timestamps"


def test_original_rolling_gate_still_rejects_seven_bad_dc_samples() -> None:
    records = []
    for i in range(60):
        sample = _observation()
        sample.timestamp = NOW + timedelta(seconds=i * 25)
        sample.foxess_balance_probe = {
            **sample.foxess_balance_probe,
            "observed_after_snapshot_at": (
                sample.timestamp + timedelta(seconds=1)
            ).isoformat(),
        }
        for role in ("inverter_ac_output", "grid_ct"):
            sample.foxess_balance_probe[role] = {
                **sample.foxess_balance_probe[role],
                "last_reported": (sample.timestamp - timedelta(seconds=1)).isoformat(),
            }
        if i >= 7:
            sample.battery_power_kw = 1.846
            sample.grid_export_kw = 1.5
            sample.house_load_kw = 0.346
            sample.foxess_balance_probe["inverter_ac_output"]["value"] = 1.846
            sample.foxess_balance_probe["grid_ct"]["value"] = 1.5
        records.append(sample)
    assessed = assess_foxess_power_balance(records, positive_is_discharge=True)
    assert not assessed.ready
    assert assessed.balanced_samples == 53
    assert assessed.balance_percent == 88.3
    assert assessed.ac_side_audit is not None
    assert assessed.ac_side_audit["informational_only"]
    assert not assessed.ac_side_audit["hardware_write_authorised"]
    assert assessed.failed_samples[0]["foxess_ac_cross_check"]["status"] == (
        "ac_cross_check_pass"
    )


@pytest.mark.parametrize(
    "clock,dc_kw,ac_kw,ct_kw,house_kw",
    [
        # Seven real Alpha9.117 failures, joined to KH7 History within 9.4 s.
        ("06:34:24", 1.516, 1.397, -0.006, 0.346),
        ("06:36:37", 1.519, 1.398, 0.017, 0.362),
        ("06:41:03", 1.513, 1.398, -0.012, 0.349),
        ("06:43:16", 1.520, 1.400, -0.009, 0.356),
        ("06:52:10", 1.397, 1.279, -0.009, 0.299),
        ("07:05:19", 1.543, 1.426, -0.014, 0.364),
        ("07:13:57", 1.469, 1.342, -0.019, 0.348),
    ],
)
def test_21_oct_seven_live_commissioning_failures_are_ac_ct_load_disagreements(
    clock: str,
    dc_kw: float,
    ac_kw: float,
    ct_kw: float,
    house_kw: float,
) -> None:
    """The missing 1kW is on the CT/load boundary, not DC-to-AC loss.

    These are REAL recorded values from a single KH7. The reported grid split
    is derived from signed CT and thus is NOT an independent validation.
    Do not waive either the failed-commissioning threshold or DNO/EV guards.
    """
    hours, minutes, seconds = (int(piece) for piece in clock.split(":"))
    timestamp = datetime(2026, 10, 21, hours - 1, minutes, seconds, tzinfo=UTC)
    sample = _observation(
        battery_kw=dc_kw,
        inverter_kw=ac_kw,
        ct_kw=ct_kw,
        house_kw=house_kw,
        import_kw=max(-ct_kw, 0.0),
        export_kw=max(ct_kw, 0.0),
    )
    sample.timestamp = timestamp
    sample.foxess_balance_probe["observed_after_snapshot_at"] = (
        timestamp + timedelta(milliseconds=100)
    ).isoformat()
    for role in ("inverter_ac_output", "grid_ct"):
        sample.foxess_balance_probe[role]["last_reported"] = (
            timestamp - timedelta(seconds=9)
        ).isoformat()
    sample.source_age_seconds["house_load_kw"] = 9.0

    result = assess_foxess_ac_side_sample(sample)
    assert result["status"] == "ac_load_mismatch"
    assert result["ac_load_residual_kw"] > 0.9
    assert 0.10 <= result["battery_dc_minus_inverter_ac_kw"] <= 0.14
    assert result["ct_split_residual_kw"] == pytest.approx(0.0)
    assert not result["independent_load_proven"]
    assert not result["hardware_write_authorised"]


def test_21_oct_adjacent_one_kw_export_is_ac_consistent() -> None:
    """Same stage and battery power, but a 1.052kW positive CT reading."""
    sample = _observation(
        battery_kw=1.513,
        inverter_kw=1.397,
        ct_kw=1.052,
        house_kw=0.345,
        import_kw=0.0,
        export_kw=1.052,
    )
    result = assess_foxess_ac_side_sample(sample)
    assert result["status"] == "ac_cross_check_pass"
    assert result["ac_load_residual_kw"] == pytest.approx(0.0)
    assert not result["hardware_write_authorised"]


def test_same_path_load_probe_never_grants_commissioning() -> None:
    """Only compare live shared-path registers; mode context stays diagnostic."""
    sample = _observation()
    sample.foxess_balance_probe["inverter_reported_load"] = {
        "value": 0.346,
        "unit": "kW",
    }
    bad = assess_foxess_power_balance([sample] * 12, positive_is_discharge=True)
    assert not bad.ready
    assert bad.balance_percent == 0.0
    probe = bad.failed_samples[0]["foxess_mode_probe"]
    assert probe["inverter_reported_load"]["value"] == 0.346
    assert probe["force_discharge_stage_kw"] == 1.0
    assert probe["last_applied_action"] == "force_discharge"
    assert "ct2_meter" not in probe
    assert "eps_ac_output" not in probe
    assert bad.failed_samples[0]["foxess_ac_cross_check"]["informational_only"]
    assert not bad.failed_samples[0]["foxess_ac_cross_check"][
        "hardware_write_authorised"
    ]


def test_21_oct_ct_changes_one_kw_while_inverter_and_house_remain_stable() -> None:
    """History confirms CT-only transition, not a DC/AC efficiency mismatch."""
    before = _observation(
        battery_kw=1.513,
        inverter_kw=1.397,
        ct_kw=1.052,
        house_kw=0.346,
        import_kw=0.0,
        export_kw=1.052,
    )
    after = _observation(
        battery_kw=1.519,
        inverter_kw=1.398,
        ct_kw=0.017,
        house_kw=0.362,
        import_kw=0.0,
        export_kw=0.017,
    )
    previous = assess_foxess_ac_side_sample(before)
    current = assess_foxess_ac_side_sample(after)
    assert previous["status"] == "ac_cross_check_pass"
    assert previous["ac_load_residual_kw"] == pytest.approx(-0.001)
    assert current["status"] == "ac_load_mismatch"
    assert current["ac_load_residual_kw"] == pytest.approx(1.019)
    assert abs(after.battery_power_kw - before.battery_power_kw) < 0.01
    assert (
        abs(
            after.foxess_balance_probe["inverter_ac_output"]["value"]
            - before.foxess_balance_probe["inverter_ac_output"]["value"]
        )
        < 0.01
    )
    assert abs(after.house_load_kw - before.house_load_kw) < 0.02
    assert (
        abs(
            after.foxess_balance_probe["grid_ct"]["value"]
            - before.foxess_balance_probe["grid_ct"]["value"]
        )
        > 1.0
    )
    assert not current["hardware_write_authorised"]


def test_constant_zero_ct2_is_not_a_secondary_source_proof() -> None:
    """The flat -0.0kW CT2 history cannot resolve the KH7 grid mismatch."""
    sample = _observation(
        battery_kw=1.519,
        inverter_kw=1.398,
        ct_kw=0.017,
        house_kw=0.362,
        import_kw=0.0,
        export_kw=0.017,
    )
    sample.foxess_balance_probe["ct2_meter"] = {
        "value": -0.0,
        "unit": "kW",
        "last_reported": "2026-10-21T05:30:00+00:00",
    }
    result = assess_foxess_ac_side_sample(sample)
    assert result["status"] == "ac_load_mismatch"
    assert not result["independent_load_proven"]
    assert not result["hardware_write_authorised"]


@pytest.mark.parametrize(
    "dc_kw,ac_kw,ct_kw,house_kw",
    [
        (1.516, 1.397, -0.006, 0.346),
        (1.519, 1.398, 0.017, 0.362),
        (1.513, 1.398, -0.012, 0.349),
        (1.520, 1.400, -0.009, 0.356),
        (1.397, 1.279, -0.009, 0.299),
        (1.543, 1.426, -0.014, 0.364),
        (1.469, 1.342, -0.019, 0.348),
    ],
)
def test_real_ct_conflicts_are_inconclusive_at_staged_export(
    dc_kw: float, ac_kw: float, ct_kw: float, house_kw: float
) -> None:
    """Seven recorded anomalies must not be mistaken for failed inverter writes."""
    sample = _observation(
        battery_kw=dc_kw,
        inverter_kw=ac_kw,
        ct_kw=ct_kw,
        house_kw=house_kw,
        import_kw=max(-ct_kw, 0.0),
        export_kw=max(ct_kw, 0.0),
    )
    assert paid_export_stage_ct_conflict(sample)
    assert not assess_foxess_ac_side_sample(sample)["hardware_write_authorised"]


def test_healthy_one_kw_export_remains_eligible_for_physical_proof() -> None:
    sample = _observation(
        battery_kw=1.513,
        inverter_kw=1.397,
        ct_kw=1.052,
        house_kw=0.345,
        import_kw=0.0,
        export_kw=1.052,
    )
    assert not paid_export_stage_ct_conflict(sample)
    assert assess_foxess_ac_side_sample(sample)["status"] == "ac_cross_check_pass"


@pytest.mark.parametrize(
    "changes",
    [
        {"inverter_kw": 0.34, "ct_kw": -0.006, "house_kw": 0.346},
        {"battery_kw": 0.0},
        {"battery_kw": -1.516},
        {"inverter_kw": 3.0},
        {"ct_kw": 0.4, "export_kw": 0.4},
        {"report_lag_seconds": 90.0},
        {"age_seconds": 90.0},
    ],
)
def test_ct_conflict_does_not_hide_other_failure_types(
    changes: dict[str, object],
) -> None:
    defaults: dict[str, object] = dict(
        battery_kw=1.519,
        inverter_kw=1.398,
        ct_kw=0.017,
        house_kw=0.362,
        import_kw=0.0,
        export_kw=0.017,
    )
    defaults.update(changes)
    assert not paid_export_stage_ct_conflict(_observation(**defaults))


def test_ct_conflict_does_not_hide_solar_missing_or_stale_proof() -> None:
    sample = _observation(
        battery_kw=1.519,
        inverter_kw=1.398,
        ct_kw=0.017,
        house_kw=0.362,
        import_kw=0.0,
        export_kw=0.017,
    )
    sample.solar_power_kw = 1.0
    assert not paid_export_stage_ct_conflict(sample)
    sample.solar_power_kw = 0.0
    sample.foxess_balance_probe = {}
    assert not paid_export_stage_ct_conflict(sample)
    sample = _observation(
        battery_kw=1.519,
        inverter_kw=1.398,
        ct_kw=0.017,
        house_kw=0.362,
        import_kw=0.0,
        export_kw=0.017,
    )
    sample.stale_fields = ("grid_import_kw",)
    assert not paid_export_stage_ct_conflict(sample)


def test_backend_checks_ct_conflict_before_three_strike_block() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "custom_components/kems/foxess_control_backend.py"
    ).read_text(encoding="utf-8")
    stage = source.split("async def _async_observe_paid_export_stage(", 1)[1]
    stage = stage.split("async def _async_restore(", 1)[0]
    check_at = stage.index("and paid_export_stage_ct_conflict(")
    fail_at = stage.index("self._paid_export_stage_failures += 1")
    assert check_at < fail_at
    assert "self._paid_export_stage_samples = 0" in stage[check_at:fail_at]
    assert "self._paid_export_stage_failures += 1" not in stage[check_at:fail_at]
    assert "self._paid_export_stage_blocked = True" in stage[fail_at:]


def _history_pair(
    *,
    early_grid_kw: float = 1.074,
    late_grid_kw: float = -0.006,
    early_ac_kw: float = 1.396,
    late_ac_kw: float = 1.397,
    early_house_kw: float = 0.318,
    late_house_kw: float = 0.346,
    early_battery_kw: float = 1.516,
    late_battery_kw: float = 1.516,
    late_seconds: int = 66,
) -> tuple[SimpleNamespace, SimpleNamespace]:
    """Replay two FoxESS register cohorts from 06:33:09 and 06:34:15 BST."""
    snapshots = []
    for index, (ct, ac, house, battery) in enumerate(
        (
            (early_grid_kw, early_ac_kw, early_house_kw, early_battery_kw),
            (late_grid_kw, late_ac_kw, late_house_kw, late_battery_kw),
        )
    ):
        at = datetime(2026, 10, 21, 5, 33, 9, tzinfo=UTC)
        if index:
            at += timedelta(seconds=late_seconds)
        sample = _observation(
            battery_kw=battery,
            inverter_kw=ac,
            ct_kw=ct,
            house_kw=house,
            import_kw=max(-ct, 0.0),
            export_kw=max(ct, 0.0),
        )
        sample.timestamp = at
        sample.source_age_seconds["house_load_kw"] = 0.5
        sample.foxess_balance_probe["observed_after_snapshot_at"] = (
            at + timedelta(seconds=1)
        ).isoformat()
        for field in ("inverter_ac_output", "grid_ct"):
            sample.foxess_balance_probe[field]["last_reported"] = (
                at - timedelta(milliseconds=500)
            ).isoformat()
        snapshots.append(sample)
    return snapshots[0], snapshots[1]


def test_historical_ct_step_is_flagged_without_blame_or_write_authority() -> None:
    early, late = _history_pair()
    result = assess_foxess_ac_ct_transition(early, late)
    assert result["status"] == ("ct_export_step_without_matching_source_or_load_step")
    assert result["grid_ct_change_kw"] == pytest.approx(-1.08)
    assert result["inverter_ac_change_kw"] == pytest.approx(0.001)
    assert result["reported_house_change_kw"] == pytest.approx(0.028)
    assert result["battery_dc_change_kw"] == pytest.approx(0.0)
    assert result["seconds_between_samples"] == 66.0
    assert result["informational_only"]
    assert not result["independent_meter_proven"]
    assert not result["ct_hardware_fault_proven"]
    assert not result["hardware_write_authorised"]


def test_real_ct_transition_is_in_commissioning_diagnostics_but_cannot_pass() -> None:
    early, late = _history_pair()
    evidence = assess_foxess_power_balance(
        [early, late], minimum_samples=1, positive_is_discharge=True
    )
    assert not evidence.ready
    assert evidence.balance_percent == 50.0
    assert evidence.ac_side_audit is not None
    assert evidence.ac_side_audit["transition_status_counts"] == {
        "ct_export_step_without_matching_source_or_load_step": 1
    }
    assert len(evidence.ac_side_audit["ct_export_step_examples"]) == 1
    assert not evidence.ac_side_audit["hardware_write_authorised"]
    assert evidence.failed_samples[0]["foxess_ac_transition"]["status"] == (
        "ct_export_step_without_matching_source_or_load_step"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"late_seconds": 120},
        {"late_ac_kw": 0.30},
        {"late_house_kw": 1.4},
        {"late_battery_kw": 0.20},
        {"late_grid_kw": 0.91},
        {"early_grid_kw": 0.017},
    ],
)
def test_ct_step_audit_does_not_accuse_meter_on_normal_or_unpaired_changes(
    change: dict[str, float],
) -> None:
    early, late = _history_pair(**change)
    result = assess_foxess_ac_ct_transition(early, late)
    assert result["status"] != ("ct_export_step_without_matching_source_or_load_step")
    assert not result["hardware_write_authorised"]


def test_ct_step_audit_fails_closed_on_stale_modbus_cohort() -> None:
    early, late = _history_pair()
    late.foxess_balance_probe["grid_ct"]["last_reported"] = (
        late.timestamp - timedelta(seconds=90)
    ).isoformat()
    assert assess_foxess_ac_ct_transition(early, late)["status"] == (
        "no_comparable_transition"
    )
