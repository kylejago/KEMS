"""Regression coverage for Alpha7.28 bounded partial-horizon dispatch."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha728_bounded_partial.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
DOC = ROOT / "docs" / "agile-bounded-partial-horizon-dispatch.md"


def test_alpha728_release_remains_packaged() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "Alpha 7.28" in source
    assert "bounded partial-horizon" in source


def test_alpha728_module_parses() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha728_installs_after_alpha727() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha728_bounded_partial_horizon_patch" in loader
    assert loader.rindex(
        "install_alpha728_bounded_partial_horizon_patch()"
    ) > loader.rindex("install_alpha727_price_recovery_patch()")


def test_alpha728_only_unlocks_verified_upstream_price_gaps() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '_UPSTREAM_MISSING_OUTCOME = "octopus_missing_price"' in source
    assert 'diagnostics.get("primary_fetch_status") == "success"' in source
    assert 'diagnostics.get("recovery_outcome") == _UPSTREAM_MISSING_OUTCOME' in source
    assert "octopus_slot_not_published" in source
    assert "octopus_no_results" in source
    assert "missing_labels.issubset(unresolved)" in source
    assert "missing_labels.issubset(relevant_attempts)" in source


def test_alpha728_keeps_retrieval_failures_on_full_hold() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "one or more relevant retries were retrieval failures or ambiguous" in source
    assert "if not eligible:" in source
    assert "return" in source
    assert '"bounded_partial_horizon_dispatch_active": False' in source


def test_alpha728_requires_full_unknown_slot_capacity_reservation() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "alpha726._future_missing_capacity_kwh" in source
    assert "_RESERVE_TOLERANCE_KWH = 0.01" in source
    assert 'plan.get("provisional_reserved_unknown_capacity_kwh")' in source
    assert '"bounded_unknown_capacity_required_kwh"' in source
    assert '"bounded_unknown_capacity_reserved_kwh"' in source
    assert '"bounded_unknown_capacity_sufficient"' in source
    assert "full unresolved-slot discharge capacity has not been reserved" in source


def test_alpha728_never_selects_an_unknown_price_slot() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "_selected_by_start" in source
    assert 'plan.get("provisional_selected_slots", [])' in source
    assert '"bounded_unknown_slot_dispatch_blocked": True' in source
    assert '"unknown_slot_dispatch_blocked": True' in source
    assert "current Agile settlement price is unknown" in source


def test_alpha728_routes_current_slot_through_existing_dispatch_limits() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "alpha717._dispatch_targets(" in source
    assert 'targets.get("battery_export_target_kw")' in source
    assert 'targets.get("battery_discharge_target_kw")' in source
    assert 'targets.get("house_battery_kw")' in source
    assert '"bounded_underlying_dispatch_mode": targets.get("mode")' in source


def test_alpha728_replaces_only_the_verified_horizon_hold() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'was_held = bool(plan.get("price_horizon_battery_export_held"))' in source
    assert '"price_horizon_battery_export_held": False' in source
    assert '"price_horizon_status": "bounded_partial_horizon"' in source
    assert '"dispatch_blocked_for_price_horizon": False' in source
    assert '"bounded_partial_horizon_dispatch_active": True' in source


def test_alpha728_extends_nonzero_proof_without_weakening_strict_checks() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "alpha725._candidate_applied_replay(result, config)" in source
    assert '"verified_octopus_missing_price"' in source
    assert '"unknown_capacity_fully_reserved"' in source
    assert '"unknown_slot_dispatch_blocked"' in source
    assert '"independent_safety_13_of_13"' in source
    assert 'safety.get("passed_checks") == 13' in source
    assert 'safety.get("total_checks") == 13' in source
    assert '"strict_tracking_100_percent"' in source
    assert 'tracking.get("tracking_score_percent") == 100.0' in source
    assert '"discharge_within_limit"' in source
    assert '"kh7_ac_within_limit"' in source
    assert '"minimum_soc_respected"' in source


def test_alpha728_proof_records_bounded_basis_without_faking_completeness() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"dispatch_basis": "bounded_partial_horizon"' in source
    assert (
        '"price_horizon_complete": result.get("price_horizon_complete") is True'
        in source
    )
    assert '"price_horizon_safe_for_dispatch": True' in source
    assert "PASS — non-zero Agile export proof" in source
    assert "CHECK — non-zero Agile export proof" in source


def test_alpha728_publishes_first_class_bounded_dispatch_evidence() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "sensor.kems_agile_partial_horizon_dispatch" in source
    assert "ACTIVE — bounded known-price dispatch" in source
    assert "Ready — bounded partial horizon" in source
    assert "Bounded partial" in source
    assert '"hardware_writes": "blocked"' in source


def test_alpha728_remains_hardware_write_blocked() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert 'result["safe_to_write_hardware"] = False' in source
    assert "Real FoxESS hardware" in source


def test_alpha728_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.28" in source
    assert "octopus_missing_price" in source
    assert "bounded_partial_horizon" in source
    assert "13/13" in source
    assert "0.01 kW" in source
    assert "10%" in source
    assert "Real FoxESS hardware writes remain blocked" in source
