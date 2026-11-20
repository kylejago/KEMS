"""The supervised solar-mode pilot is advisory until independent KH7 proof exists."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "kems"
SPEC = importlib.util.spec_from_file_location(
    "solar_routing_pilot_under_test", ROOT / "solar_routing_pilot.py"
)
assert SPEC is not None and SPEC.loader is not None
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)


def _candidate():
    return {
        "status": "feed_in_first_candidate",
        "scope": "shadow_only",
        "hardware_writes": "forbidden",
        "bounded_redirectable_solar_kw": 2.5,
        "advantage_pence_per_input_kwh": 7.0,
        "expected_advantage_pence": 8.0,
        "physical_solar_flow": {"status": "bounded_physical_inference"},
    }


def _snapshot():
    return SimpleNamespace(
        ev_connected=False,
        ev_charging=False,
        off_peak=False,
        tariff_stale_fields=(),
        saving_session_active=False,
        stale_fields=(),
        source_age_seconds={
            "solar_power_kw": 5.0,
            "house_load_kw": 6.0,
            "battery_power_kw": 6.0,
            "grid_import_kw": 6.0,
            "grid_export_kw": 6.0,
            "battery_soc": 7.0,
        },
    )


def _readback(source="sensor_readback", mode="Self Use", status="PASS"):
    return {"value": mode, "status": status, "observation_source": source}


def test_actual_kh7_command_entity_cannot_prove_mode_or_authorise_writes():
    result = pilot.assess_solar_pilot_readiness(
        solar_shadow=_candidate(),
        snapshot=_snapshot(),
        work_mode_observation=_readback("command_entity"),
    )
    assert result["financial_candidate"] is True
    assert result["status"] == "candidate_needs_pilot_evidence"
    assert "independent_kh7_work_mode_readback_not_proven" in result["missing_evidence"]
    assert "independent_baseline_rollback_not_proven" in result["missing_evidence"]
    assert result["hardware_writes"] == "forbidden"
    assert result["live_mode_switching_enabled"] is False


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("ev_connected", True, "ev_disconnection_not_independently_confirmed"),
        ("ev_charging", True, "ev_idle_not_independently_confirmed"),
        ("off_peak", True, "offpeak_or_unknown_tariff"),
        ("saving_session_active", True, "power_down_or_unknown_event"),
        ("tariff_stale_fields", ("off_peak",), "tariff_source_staleness_reported"),
    ],
)
def test_priority_sources_never_allow_unverified_solar_mode(field, value, reason):
    snap = _snapshot()
    setattr(snap, field, value)
    result = pilot.assess_solar_pilot_readiness(
        solar_shadow=_candidate(),
        snapshot=snap,
        work_mode_observation=_readback(),
        baseline_restoration_proven=True,
    )
    assert reason in result["missing_evidence"]
    assert result["live_mode_switching_enabled"] is False


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("solar_power_kw", 130.0, "solar_power_kw_not_fresh_for_pilot"),
        ("grid_export_kw", None, "grid_export_kw_not_fresh_for_pilot"),
        ("battery_soc", 91.0, "physical_soc_not_fresh_for_pilot"),
    ],
)
def test_pilot_requires_fresh_independent_physical_sources(field, value, reason):
    snap = _snapshot()
    snap.source_age_seconds[field] = value
    result = pilot.assess_solar_pilot_readiness(
        solar_shadow=_candidate(),
        snapshot=snap,
        work_mode_observation=_readback(),
        baseline_restoration_proven=True,
    )
    assert reason in result["missing_evidence"]


def test_missing_pv_attribution_blocks_mode_pilot():
    c = _candidate()
    c["physical_solar_flow"] = {"status": "measured_only"}
    r = pilot.assess_solar_pilot_readiness(
        solar_shadow=c,
        snapshot=_snapshot(),
        work_mode_observation=_readback(),
        baseline_restoration_proven=True,
    )
    assert "pv_to_battery_contribution_not_physically_bounded" in r["missing_evidence"]


@pytest.mark.parametrize(
    "key,value,reason",
    [
        ("bounded_redirectable_solar_kw", 0.1, "redirectable_solar_too_small_or_unknown"),
        ("advantage_pence_per_input_kwh", 0.2, "economic_margin_too_small_or_unknown"),
        ("expected_advantage_pence", 0.7, "expected_total_benefit_too_small_or_unknown"),
        ("expected_advantage_pence", float("nan"), "expected_total_benefit_too_small_or_unknown"),
    ],
)
def test_noise_and_small_pence_benefits_cannot_qualify(key, value, reason):
    c = _candidate()
    c[key] = value
    r = pilot.assess_solar_pilot_readiness(
        solar_shadow=c,
        snapshot=_snapshot(),
        work_mode_observation=_readback(),
        baseline_restoration_proven=True,
    )
    assert reason in r["missing_evidence"]


def test_even_synthetic_everything_proven_has_no_write_authority():
    r = pilot.assess_solar_pilot_readiness(
        solar_shadow=_candidate(),
        snapshot=_snapshot(),
        work_mode_observation=_readback(),
        baseline_restoration_proven=True,
    )
    assert r["status"] == "prerequisites_observed"
    assert r["missing_evidence"] == []
    assert r["supervised_pilot_prerequisites_observed"] is True
    assert r["advisory_only"] is True
    assert r["hardware_writes"] == "forbidden"
    assert r["live_mode_switching_enabled"] is False


def test_storage_decision_is_not_a_feed_in_candidate():
    c = _candidate()
    c["status"] = "keep_self_use"
    r = pilot.assess_solar_pilot_readiness(
        solar_shadow=c,
        snapshot=_snapshot(),
        work_mode_observation=_readback(),
        baseline_restoration_proven=True,
    )
    assert r["status"] == "not_candidate"
    assert r["financial_candidate"] is False
    assert "no_economic_feed_in_first_candidate" in r["missing_evidence"]


def test_coordinator_publishes_pilot_evidence_outside_physical_writer():
    src = (ROOT / "coordinator.py").read_text(encoding="utf-8")
    start = src.index("solar_shadow = evaluate_solar_routing_shadow(")
    pilot_at = src.index("assess_solar_pilot_readiness(", start)
    publish_at = src.index("publish_solar_routing_shadow(", start)
    assert start < pilot_at < publish_at
    assert 'work_mode_observation=balance_probe.get("work_mode")' in src
    assert "solar_shadow[\"pilot_readiness\"]" in src
    physical = (ROOT / "foxess_control_backend.py").read_text(encoding="utf-8")
    assert "solar_routing_pilot" not in physical
