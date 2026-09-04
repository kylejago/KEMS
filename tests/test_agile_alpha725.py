"""Regression coverage for alpha7.25 Agile non-zero export proof."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha725_nonzero.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "agile-nonzero-export-proof.md"


def test_alpha725_patch_remains_packaged() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert any(
        marker in manifest
        for marker in ('"version": "0.8.0-alpha8.', '"version": "0.9.0-alpha9.')
    )
    assert PATCH.exists()


def test_alpha725_module_parses() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha725_installs_after_alpha724() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha725_nonzero_export_proof_patch" in loader
    assert loader.rindex(
        "install_alpha725_nonzero_export_proof_patch()"
    ) > loader.rindex("install_alpha724_outcome_parity_patch()")


def test_alpha725_requires_genuine_nonzero_target_and_complete_horizon() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "NONZERO_EXPORT_THRESHOLD_KW = 0.01" in source
    assert 'result.get("price_horizon_complete") is True' in source
    assert 'result.get("battery_export_held")' in source
    assert (
        "qualified = bool(nonzero and horizon_complete and not horizon_held)" in source
    )
    assert "WAITING — non-zero Agile export target" in source
    assert "WAITING — complete Agile price horizon" in source


def test_alpha725_uses_candidate_applied_digital_twin_replay() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"candidate_applied_digital_twin"' in source
    assert 'routing.get("total_kh7_ac_output_kw")' in source
    assert 'routing.get("base_digital_twin_discharge_kw")' in source
    assert "routed_solar_ac = max(base_ac - base_discharge, 0.0)" in source
    assert (
        "available_discharge = min(config.max_discharge_kw, inverter_headroom)"
        in source
    )
    assert "replay_export = min(" in source
    assert "config.export_limit_kw" in source


def test_alpha725_requires_strict_tracking_and_retains_baseline_evidence() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "STRICT_TRACKING_TOLERANCE_KW = 0.01" in source
    assert '"strict_tracking_100_percent"' in source
    assert 'result["baseline_tracking"]' in source
    assert 'result["baseline_outcome_parity"]' in source
    assert 'result["tracking"] = tracking' in source
    assert 'result["outcome_parity_passed"] = passed' in source


def test_alpha725_requires_full_safety_and_system_limits() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"independent_safety_13_of_13"' in source
    assert 'safety.get("passed_checks") == 13' in source
    assert 'safety.get("total_checks") == 13' in source
    assert '"discharge_within_limit"' in source
    assert '"kh7_ac_within_limit"' in source
    assert '"minimum_soc_respected"' in source
    assert "config.normal_reserve_percent" in source


def test_alpha725_nonzero_pass_has_feed_in_first_and_export_permission() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"feed_in_first_mode"' in source
    assert 'candidate.get("desired_work_mode") == "Feed-in First"' in source
    assert '"grid_export_allowed"' in source
    assert "PASS — non-zero Agile export proof" in source
    assert "CHECK — non-zero Agile export proof" in source


def test_alpha725_persists_proof_evidence_and_dashboard() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'latest["nonzero_export_proof_state"]' in source
    assert 'latest["nonzero_export_proof_passed"]' in source
    assert 'latest["strict_tracking_score_percent"]' in source
    assert 'latest["replay_battery_export_kw"]' in source
    assert "Agile optimiser → command → non-zero replay" in source
    assert "Strict tracking:" in source


def test_alpha725_remains_hardware_write_blocked() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".async_call(" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert '"hardware_writes": "blocked"' in source
    assert 'result["safe_to_write_hardware"] = False' in source
    assert "never permits hardware commands" in source


def test_alpha725_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.25" in source
    assert "genuine non-zero battery export" in source
    assert "0.01 kW" in source
    assert "13/13" in source
    assert "7 kW" in source
    assert "10%" in source
    assert "real hardware writes remain blocked" in source
