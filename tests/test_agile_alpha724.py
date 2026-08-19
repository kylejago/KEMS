"""Regression coverage for alpha7.24 Agile shadow outcome parity."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha724_outcome.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "agile-shadow-outcome-parity.md"


def test_alpha724_manifest_is_exact() -> None:
    assert '"version": "0.7.0-alpha7.24"' in MANIFEST.read_text(encoding="utf-8")


def test_alpha724_module_parses() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha724_installs_after_alpha723() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha724_outcome_parity_patch" in loader
    assert loader.rindex("install_alpha724_outcome_parity_patch()") > loader.rindex(
        "install_alpha723_shadow_patch()"
    )


def test_alpha724_uses_same_proposal_solar_path_as_agile_replay() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "rolling._current_house_headroom_kw" in source
    assert "simulator._simulated_solar_power(current, config)" in source
    assert '"same proposal/live solar path as Agile replay"' in source
    assert "max(house - solar, 0.0)" in source


def test_alpha724_normalises_ac_output_without_clipping_battery_target() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "current_simulated_total_kh7_output_kw" in source
    assert "base_ac) - base_discharge + candidate_discharge" in source
    assert "candidate.desired_total_discharge_power_kw" in source
    assert "total_kh7_ac_output_kw=round(normalised_ac, 3)" in source
    assert "kh7_output_headroom_kw=round(" in source


def test_alpha724_keeps_alpha723_optimizer_and_safety_chain() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "_ORIGINAL_BUILD" in source
    assert "_ORIGINAL_EVALUATE" in source
    assert "outcome_parity_passed" in source
    assert 'result["status"] = "CHECK — shadow outcome mismatch"' in source
    assert "independent 13-point" in source


def test_alpha724_records_tracking_evidence() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'latest["tracking_score_percent"]' in source
    assert 'latest["outcome_parity_passed"]' in source
    assert 'latest["outcome_routing_basis"]' in source
    assert "Agile optimiser → shadow command → outcome" in source
    assert "Tracking score:" in source
    assert "Outcome parity:" in source


def test_alpha724_remains_hardware_write_blocked() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".async_call(" not in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "It is not sent to FoxESS." in source
    assert "never permits hardware commands" in source


def test_alpha724_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.24" in source
    assert "proposal/live solar" in source
    assert "50%" in source
    assert "hardware writes remain blocked" in source
