"""Regression coverage for alpha7.26 provisional Agile planning."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha726_provisional.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "agile-provisional-planning-bst-horizon.md"


def test_alpha726_patch_remains_packaged() -> None:
    manifest = MANIFEST.read_text(encoding="utf-8")
    assert any(
        marker in manifest
        for marker in ('"version": "0.8.0-alpha8.', '"version": "0.9.0-alpha9.')
    )
    assert PATCH.exists()


def test_alpha726_module_parses() -> None:
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha726_installs_after_alpha725() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha726_provisional_planning_patch" in loader
    assert loader.rindex(
        "install_alpha726_provisional_planning_patch()"
    ) > loader.rindex("install_alpha725_nonzero_export_proof_patch()")


def test_alpha726_keeps_dispatch_held_but_preserves_economic_plan() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "alpha722_original_hold(state, plan, horizon, now=now)" in source
    assert 'plan["dispatch_permitted_battery_export_kw"] = 0.0' in source
    assert 'plan["provisional_selected_slots"]' in source
    assert 'plan["provisional_planned_battery_export_kwh"]' in source
    assert 'plan["dispatch_blocked_for_price_horizon"] = True' in source
    assert '"economic_plan_status": plan.get("economic_plan_status")' in source


def test_alpha726_reserves_capacity_for_unknown_price_slots() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "_future_missing_capacity_kwh" in source
    assert "_reserve_unknown_capacity" in source
    assert 'plan["provisional_reserved_unknown_capacity_kwh"]' in source
    assert 'plan["provisional_unresolved_price_slots"]' in source
    assert "lowest-priced known allocations" in source


def test_alpha726_targeted_retry_is_exact_and_never_invents_rates() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "MAX_TARGETED_RATE_RETRIES = 4" in source
    assert '"period_from": agile._api_dt(start)' in source
    assert '"period_to": agile._api_dt(end)' in source
    assert "AgileRate.from_dict" in source
    assert 'diagnostics["targeted_retry_recovered"]' in source
    assert 'diagnostics["unresolved_missing_labels"]' in source
    assert "expected_slots_for_day(local_day, agile.LONDON)" in source
    assert "missing_slots_for_day" in source


def test_alpha726_publishes_hold_and_provisional_soc_outcomes() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'hold["hold_projected_deadline_soc_percent"]' in source
    assert 'hold["provisional_known_price_deadline_soc_percent"]' in source
    assert 'hold["provisional_projected_deadline_soc_percent"]' in source
    assert 'hold["provisional_points"]' in source
    assert "If safety hold continues" in source
    assert "With provisional economic plan" in source


def test_alpha726_dashboard_separates_economic_plan_from_dispatch() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "Upcoming Agile economic plan vs dispatch" in source
    assert "| Time | Rate | Economic plan | Provisional export | Dispatch |" in source
    assert "sensor.kems_agile_provisional_export_plan" in source
    assert "sensor.kems_agile_price_fetch_diagnostics" in source
    assert "BLOCKED — price horizon incomplete" in source


def test_alpha726_keeps_nonzero_proof_and_hardware_safety_boundaries() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "agile_alpha722_horizon" in source
    assert "agile_alpha719_validation" in source
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert '"hardware_writes": "blocked"' in source
    assert "never permits FoxESS hardware writes" in source


def test_alpha726_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.26" in source
    assert "economic planning" in source
    assert "dispatch permission" in source
    assert "23:00 and 23:30 BST" in source
    assert "reserved" in source
    assert "real FoxESS hardware writes remain blocked" in source
